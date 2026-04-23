# """
# Saturation Analysis Service  — v3
# ===================================
# Implements client's exact 2-step PHREEQC workflow:

#   Step 1-3  (per CoC):
#     SOLUTION at cold basin temp + EQUILIBRIUM_PHASES CO2(g)
#     → Calculates natural pH after CO2 degassing

#   Step 5-6  (per CoC):
#     SOLUTION at hot evaluation temp, pH from Step 3, Cl charge balance
#     → Final SI values used for graph and display

# CO2 partial pressure is auto-calculated from tower type:
#   Base -3.4 + airflow + fill + draft + approach_to_WB adjustments

# Special cases:
#   Evaporative Condenser → base -3.4, no correction
#   Once Through Cooling  → no EQUILIBRIUM_PHASES at all

# Public methods:
#   run_analysis(request_dict)   → full pipeline
#   switch_salt(run_id, salt_id) → re-graph from saved DB data (no re-run)
#   get_available_salts()        → PHREEQC mineral list (cached)
# """

# import io
# import logging
# import math
# import os
# import re
# import uuid
# from datetime import datetime, timezone
# from typing import Any, Dict, List, Optional, Tuple

# import boto3
# import matplotlib
# matplotlib.use("Agg")
# import matplotlib.pyplot as plt
# import numpy as np
# from botocore.exceptions import BotoCoreError, ClientError

# from app.db.mongo import db
# from app.services.phreeqc_service import PHREEQCService
# from app.services.calculation_service import CalculationService
# from app.services.cooling_tower_service import CoolingTowerService

# logger = logging.getLogger(__name__)

# # ─────────────────────────────────────────────────────────────────────────────
# # DYNAMIC WATER PARAMETER KEY MAPPER
# # Maps any OCR-extracted key → PHREEQC internal ion key
# # ─────────────────────────────────────────────────────────────────────────────
# _PARAM_ALIAS: Dict[str, str] = {
#     # Calcium
#     "calcium": "Ca", "ca": "Ca",
#     # Magnesium
#     "magnesium": "Mg", "mg": "Mg",
#     # Sodium
#     "sodium": "Na", "na": "Na",
#     # Potassium
#     "potassium": "K", "k": "K",
#     # Chloride
#     "chloride": "Cl", "cl": "Cl",
#     # Sulfate / Sulphate
#     "sulfate": "SO4", "sulphate": "SO4", "so4": "SO4",
#     # Alkalinity / Bicarbonate — NOT Total Hardness
#     "alkalinity": "HCO3", "bicarbonate": "HCO3", "hco3": "HCO3",
#     "total_alkalinity": "HCO3", "m_alkalinity": "HCO3",
#     # Silica
#     "silica": "SiO2", "sio2": "SiO2", "silicon": "SiO2",
#     # Barium
#     "barium": "Ba", "ba": "Ba",
#     # Strontium
#     "strontium": "Sr", "sr": "Sr",
#     # Iron
#     "iron": "Fe", "fe": "Fe",
#     # pH
#     "ph": "pH",
#     # Temperature
#     "temperature": "Temperature", "temp": "Temperature",
#     # Nitrate
#     "nitrate": "NO3", "no3": "NO3",
#     # Fluoride
#     "fluoride": "F", "f": "F",
#     # Phosphate
#     "phosphate": "PO4", "po4": "PO4",
#     # Manganese
#     "manganese": "Mn", "mn": "Mn",
#     # Potassium (alternate)
#     "k_": "K",
# }

# # Keys to explicitly SKIP — these are not PHREEQC ions
# _SKIP_KEYS = {
#     "total_hardness", "total_dissolved_solids", "tds",
#     "electrical_conductivity", "conductivity", "turbidity",
#     "total_coliform", "e_coli", "fecal_coliform",
#     "bod", "cod", "toc",
#     "arsenic", "lead", "cadmium", "chromium", "mercury",
#     "cyanide", "phenolic_compounds", "nitrite",
# }

# # pH adjustment rules per chemical
# _PH_RULES: Dict[str, Dict[str, float]] = {
#     "H2SO4": {"HCO3": -1.00, "SO4": +1.00},
#     "HCL":   {"HCO3": -1.37, "Cl":  +0.97},
#     "NAOH":  {"HCO3": +1.25, "Na":  +0.57},
# }

# # Colour hex values
# _COLOUR_HEX = {"green": "#2ECC71", "yellow": "#F1C40F", "red": "#E74C3C", "error": "#BDC3C7"}


# def _map_water_params(raw: Dict[str, Any]) -> Dict[str, Any]:
#     """
#     Convert dynamic OCR keys → internal PHREEQC ion keys.
#     Preserves unit information for unit-aware PHREEQC input building.
#     Returns dict: { ion_key: {"value": float, "unit": str} }
#     """
#     out: Dict[str, Any] = {}
#     for key, val in raw.items():
#         norm = key.lower().replace(" ", "_").replace("-", "_")

#         # Explicitly skip non-ion parameters
#         if norm in _SKIP_KEYS:
#             continue

#         ion = _PARAM_ALIAS.get(norm)
#         if ion is None:
#             skip_match = any(s in norm for s in ["hardness", "dissolved_solid", "conductivity",
#                                                    "coliform", "turbidity", "phenol"])
#             if skip_match:
#                 continue
#             for alias, mapped in _PARAM_ALIAS.items():
#                 if alias in norm or norm in alias:
#                     ion = mapped
#                     break
#         if ion is None:
#             continue

#         # Extract numeric value and unit
#         if isinstance(val, dict):
#             numeric = val.get("value")
#             unit    = val.get("unit", "mg/L") or "mg/L"
#         elif isinstance(val, (int, float)):
#             numeric = val
#             unit    = "mg/L"
#         else:
#             continue

#         if numeric is None:
#             continue
#         try:
#             numeric = float(numeric)
#         except (TypeError, ValueError):
#             continue

#         if ion != "pH" and numeric <= 0:
#             continue

#         # Store with unit for unit-aware PHREEQC input
#         out[ion] = {"value": numeric, "unit": unit.strip()}

#     return out


# def _get_ion_value(mapped: Dict[str, Any], ion: str) -> Optional[float]:
#     """Get numeric value from mapped params."""
#     v = mapped.get(ion)
#     if v is None:
#         return None
#     if isinstance(v, dict):
#         return float(v.get("value", 0))
#     return float(v)


# def _get_ion_unit(mapped: Dict[str, Any], ion: str) -> str:
#     """Get unit from mapped params."""
#     v = mapped.get(ion)
#     if isinstance(v, dict):
#         return v.get("unit", "mg/L") or "mg/L"
#     return "mg/L"


# def _apply_ph_adjustment(params: Dict[str, Any], chemical: Optional[str]) -> Dict[str, Any]:
#     """Adjust alkalinity + counterion based on pH chemical."""
#     if not chemical:
#         return dict(params)
#     rules = _PH_RULES.get(chemical.upper().replace("-", "").replace("_", ""))
#     if not rules:
#         logger.warning(f"Unknown pH chemical '{chemical}', skipping adjustment")
#         return dict(params)
#     adjusted = dict(params)
#     for ion, factor in rules.items():
#         entry = adjusted.get(ion)
#         if isinstance(entry, dict):
#             current = float(entry.get("value", 0.0))
#             adjusted[ion] = {**entry, "value": max(0.0, current + factor)}
#         else:
#             current = float(entry) if entry is not None else 0.0
#             adjusted[ion] = max(0.0, current + factor)
#     return adjusted


# def _get_inhibited_salts(raw_material_chemistry: Optional[Dict]) -> List[str]:
#     """
#     Extract list of salt names that this raw material inhibits.
#     From inhibitionFormulas[].salToInhibit
#     """
#     if not raw_material_chemistry:
#         return []
#     formulas = raw_material_chemistry.get("inhibitionFormulas") or []
#     return [f.get("salToInhibit", "") for f in formulas if f.get("salToInhibit")]


# def _color_code_for_salt(
#     si: float,
#     salt_name: str,
#     inhibited_salts: List[str],
#     thresholds: Dict[str, Any],
# ) -> str:
#     """
#     Client color logic:

#     IF raw material inhibits this salt:
#         green  → SI < yellow_lower  (treatment working)
#         yellow → yellow_lower ≤ SI ≤ yellow_upper  (caution)
#         red    → SI > yellow_upper  (treatment not working)

#     ELSE (no inhibition for this salt):
#         green → SI < 0   (undersaturated, no scaling risk)
#         red   → SI >= 0  (supersaturated, scaling risk)
#     """
#     # Check if this salt is inhibited by the raw material (case-insensitive)
#     salt_lower = salt_name.lower()
#     is_inhibited = any(s.lower() in salt_lower or salt_lower in s.lower()
#                        for s in inhibited_salts if s)

#     if is_inhibited:
#         yellow_lower = thresholds.get("yellow_lower", -0.5)
#         yellow_upper = thresholds.get("yellow_upper",  0.5)
#         if si < yellow_lower:
#             return "green"
#         if si <= yellow_upper:
#             return "yellow"
#         return "red"
#     else:
#         # No inhibition data — simple SI < 0 = green, SI >= 0 = red
#         return "green" if si < 0 else "red"


# def _parse_thresholds(raw_material_chemistry: Optional[Dict], dosage_ppm: float = 2.0) -> Dict[str, Any]:
#     """
#     Extract color band thresholds from raw_material_chemistry.

#     Client logic:
#       Dose = f(SI)  →  solve for SI given Dose
#       Example: "Dose = 0.0358 x SI(CaCO3) + 0.5272"
#       → SI_max = (Dose - 0.5272) / 0.0358

#       Yellow band = SI_max ± band_cushion%
#       green  → SI < yellow_lower
#       yellow → yellow_lower ≤ SI ≤ yellow_upper
#       red    → SI > yellow_upper
#     """
#     if not raw_material_chemistry:
#         return {
#             "max_si_at_dose": 0.0,
#             "yellow_lower":  -0.5,
#             "yellow_upper":   0.5,
#             "band_lower_pct": 5.0,
#             "band_upper_pct": 5.0,
#             "formula_used":   None,
#         }

#     def _to_float(v, default=0.0):
#         try:
#             if isinstance(v, str):
#                 v = v.replace("%", "").strip()
#             return float(v)
#         except (TypeError, ValueError):
#             return default

#     band_lower_pct = _to_float(raw_material_chemistry.get("bandLowerCushion"), 5.0)
#     band_upper_pct = _to_float(raw_material_chemistry.get("bandUpperCushion"), 5.0)

#     # Try to solve SI_max from inhibition formula
#     si_max = None
#     formula_used = None
#     inhibition_formulas = raw_material_chemistry.get("inhibitionFormulas", [])

#     for formula_obj in (inhibition_formulas or []):
#         formula_str = formula_obj.get("formulaForInhibitionPerformance", "")
#         if not formula_str:
#             continue
#         try:
#             import re as _re
#             f = formula_str.replace("x", "*").replace("X", "*").replace("×", "*")
#             # Match: Dose = A * SI + B  or  Dose = A * SI(Salt) + B
#             m = _re.search(r"=\s*([\d.]+)\s*\*?\s*SI[^+\-]*\+\s*([\d.]+)", f)
#             if not m:
#                 m = _re.search(r"=\s*([\d.]+)\s*\*?\s*SI[^+\-]*-\s*([\d.]+)", f)
#                 if m:
#                     a, b = float(m.group(1)), -float(m.group(2))
#                 else:
#                     continue
#             else:
#                 a, b = float(m.group(1)), float(m.group(2))

#             if a != 0:
#                 si_max = (dosage_ppm - b) / a
#                 formula_used = formula_str
#                 logger.info(f"SI_max from formula at dose={dosage_ppm}: SI_max={si_max:.4f}")
#                 break
#         except Exception as e:
#             logger.warning(f"Could not parse inhibition formula '{formula_str}': {e}")

#     if si_max is None:
#         si_max = 0.0

#     yellow_lower = si_max * (1 - band_lower_pct / 100)
#     yellow_upper = si_max * (1 + band_upper_pct / 100)

#     return {
#         "max_si_at_dose":  round(si_max, 4),
#         "yellow_lower":    round(yellow_lower, 4),
#         "yellow_upper":    round(yellow_upper, 4),
#         "band_lower_pct":  band_lower_pct,
#         "band_upper_pct":  band_upper_pct,
#         "formula_used":    formula_used,
#     }


# # ─────────────────────────────────────────────────────────────────────────────
# # CO2 PARTIAL PRESSURE CALCULATOR
# # Based on client's tower type table
# # ─────────────────────────────────────────────────────────────────────────────

# # Adjustment tables from client spec
# _CO2_AIRFLOW_ADJ: Dict[str, float] = {
#     "counterflow": 0.0,
#     "crossflow":   0.15,
# }

# _CO2_FILL_ADJ: Dict[str, float] = {
#     "film fill - high-efficiency": -0.1,
#     "film fill high efficiency":   -0.1,
#     "film fill - standard":         0.0,
#     "film fill standard":           0.0,
#     "splash fill":                  0.2,
#     "splash":                       0.2,
# }

# _CO2_DRAFT_ADJ: Dict[str, float] = {
#     "forced draft":  0.0,
#     "induced draft": -0.05,
#     "natural draft":  0.15,
# }


# def _calculate_co2_factor(
#     system_type: Optional[str],
#     tower_type: Optional[str],
#     fill_type: Optional[str],
#     draft_type: Optional[str],
#     approach_to_wb: Optional[float],
#     co2_override: Optional[float],
# ) -> Optional[float]:
#     """
#     Calculate CO2(g) log partial pressure for EQUILIBRIUM_PHASES.

#     Returns:
#         float  → use this value in EQUILIBRIUM_PHASES CO2(g) <value> 100.0
#         None   → Once Through Cooling, skip EQUILIBRIUM_PHASES entirely
#     """
#     # Manual override takes priority
#     if co2_override is not None:
#         return co2_override

#     sys = (system_type or "").lower().strip()

#     # Once Through Cooling → no equilibrium phase
#     if "once" in sys and "through" in sys:
#         return None

#     # Evaporative Condenser → base only, no correction
#     if "evaporative" in sys or "condenser" in sys:
#         return -3.4

#     # Cooling Tower → apply corrections
#     base = -3.4

#     # Airflow type
#     airflow_key = (tower_type or "").lower().strip()
#     base += _CO2_AIRFLOW_ADJ.get(airflow_key, 0.0)

#     # Fill type
#     fill_key = (fill_type or "").lower().strip()
#     base += _CO2_FILL_ADJ.get(fill_key, 0.0)

#     # Draft type
#     draft_key = (draft_type or "").lower().strip()
#     base += _CO2_DRAFT_ADJ.get(draft_key, 0.0)

#     # Approach to WB
#     if approach_to_wb is not None:
#         if approach_to_wb < 5:
#             base += -0.1
#         elif approach_to_wb <= 10:
#             base += 0.0
#         elif approach_to_wb <= 15:
#             base += 0.1
#         else:
#             base += 0.2

#     logger.info(
#         f"CO2 factor: base=-3.4 → {base:.2f} "
#         f"(airflow={tower_type}, fill={fill_type}, draft={draft_type}, approach={approach_to_wb}°F)"
#     )
#     return round(base, 2)


# def _f_to_c(f: float) -> float:
#     """Fahrenheit to Celsius."""
#     return round((f - 32) * 5 / 9, 2)


# def _to_celsius(value: float, unit: str) -> float:
#     """Convert temperature to Celsius."""
#     u = (unit or "").strip().upper()
#     if u in ("F", "°F"):
#         return _f_to_c(value)
#     return round(value, 2)

#     return {
#         "max_si_at_dose": 0.0,
#         "band_lower": _to_float(raw_material_chemistry.get("bandLowerCushion"), 0.0),
#         "band_upper": _to_float(raw_material_chemistry.get("bandUpperCushion"), 0.5),
#     }


# # ─────────────────────────────────────────────────────────────────────────────
# # MAIN SERVICE
# # ─────────────────────────────────────────────────────────────────────────────

# class SaturationService:
#     """
#     Orchestrates the full saturation analysis pipeline using client's
#     exact 2-step PHREEQC workflow per CoC value.
#     """

#     COLOUR_MAP = _COLOUR_HEX

#     def __init__(self):
#         self.phreeqc   = PHREEQCService()
#         self.s3_bucket = os.getenv("AWS_S3_BUCKET_NAME") or os.getenv("AWS_S3_BUCKET", "")
#         self.s3_region = os.getenv("AWS_REGION", "us-east-1")
#         self.s3_prefix = os.getenv("AWS_S3_SATURATION_PREFIX", "saturation-graphs/")
#         self._s3       = None

#     def _get_s3(self):
#         if self._s3 is None:
#             self._s3 = boto3.client(
#                 "s3",
#                 region_name=self.s3_region,
#                 aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
#                 aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
#             )
#         return self._s3

#     # ── Build CoC list ────────────────────────────────────────────────────────
#     @staticmethod
#     def _build_coc_list(coc_min: float, coc_max: float, coc_interval: float) -> List[float]:
#         """Return list of CoC values from min to max with given interval."""
#         vals, c = [], coc_min
#         interval = max(coc_interval, 0.01)
#         while c <= coc_max + 1e-9:
#             vals.append(round(c, 4))
#             c += interval
#         if not vals:
#             vals = [coc_min]
#         return vals

#     # ── Step 1-3: CO2 equilibration at cold basin temp ────────────────────────
#     async def _step1_natural_ph(
#         self,
#         mapped_params: Dict[str, Any],
#         coc: float,
#         cold_temp_c: float,
#         co2_factor: Optional[float],
#         database: str,
#     ) -> float:
#         """
#         Run PHREEQC at cold basin temperature with CO2 equilibration.
#         Returns the natural pH after CO2 degassing.
#         Minerals multiplied by CoC (except pH, Temperature, pe).
#         """
#         if co2_factor is None:
#             return float(_get_ion_value(mapped_params, "pH") or 7.0)

#         concentrated = {}
#         skip_keys = {"pH", "Temperature", "pe"}
#         for k, v in mapped_params.items():
#             if k in skip_keys:
#                 concentrated[k] = v
#             elif isinstance(v, dict):
#                 concentrated[k] = {**v, "value": v["value"] * coc}
#             else:
#                 concentrated[k] = float(v) * coc

#         concentrated["Temperature"] = {"value": cold_temp_c, "unit": "°C"}

#         try:
#             result = await self.phreeqc.run_step1_co2_equilibration(
#                 concentrated, co2_factor, database
#             )
#             natural_ph = result.get("pH", _get_ion_value(mapped_params, "pH") or 7.0)
#             logger.debug(f"  CoC={coc} cold={cold_temp_c}°C → natural pH={natural_ph:.3f}")
#             return float(natural_ph)
#         except Exception as e:
#             logger.warning(f"Step 1-3 CO2 eq failed for CoC={coc}: {e}")
#             return float(_get_ion_value(mapped_params, "pH") or 7.0)

#     # ── Step 5-6: Final SI calculation at hot evaluation temp ─────────────────
#     async def _step5_hot_temp_si(
#         self,
#         mapped_params: Dict[str, Any],
#         coc: float,
#         hot_temp_c: float,
#         natural_ph: float,
#         balance_anion: str,
#         database: str,
#     ) -> Dict[str, Any]:
#         """
#         Run PHREEQC at hot evaluation temperature with natural pH and Cl charge balance.
#         Minerals multiplied by CoC.
#         """
#         concentrated = {}
#         skip_keys = {"pH", "Temperature", "pe"}
#         for k, v in mapped_params.items():
#             if k in skip_keys:
#                 concentrated[k] = v
#             elif isinstance(v, dict):
#                 concentrated[k] = {**v, "value": v["value"] * coc}
#             else:
#                 concentrated[k] = float(v) * coc

#         concentrated["pH"]          = {"value": natural_ph, "unit": ""}
#         concentrated["Temperature"] = {"value": hot_temp_c,  "unit": "°C"}

#         try:
#             result = await self.phreeqc.run_step5_hot_temp(
#                 concentrated, natural_ph, hot_temp_c, balance_anion, database
#             )
#             return result
#         except Exception as e:
#             logger.error(f"Step 5-6 failed for CoC={coc}, temp={hot_temp_c}°C: {e}")
#             return {"saturation_indices": [], "ionic_strength": 0.0,
#                     "charge_balance_error_pct": 0.0, "description_of_solution": {}}

#     # ── STEP: run full 2-step pipeline per CoC × Temperature ─────────────────
#     async def _run_two_step_pipeline(
#         self,
#         mapped_params: Dict[str, Any],
#         coc_list: List[float],
#         cold_temp_c: float,
#         temp_list_c: List[float],
#         co2_factor: Optional[float],
#         salt_id: Optional[str],
#         salts_of_interest: Optional[List[str]],
#         thresholds: Dict[str, Any],
#         inhibited_salts: List[str],
#         balance_cation: str,
#         balance_anion: str,
#     ) -> Tuple[List[Dict[str, Any]], str]:
#         """
#         Client pseudo-code:
#           Do CurrentTemp = temp_min to temp_max
#             Do CoC = coc_min to coc_max
#               Step 1: supply_temp + CO2 eq → natural pH
#               Step 2: CurrentTemp + natural pH + Cl charge → SI
#             Loop
#           Loop
#         """
#         # Select database based on highest CoC + highest temp
#         max_coc  = max(coc_list)
#         max_temp = max(temp_list_c)

#         database = self.phreeqc.select_database(
#             {k: v["value"] if isinstance(v, dict) else v for k, v in mapped_params.items()},
#             ph_range=(6.0, 10.0),
#             coc_range=(min(coc_list), max_coc),
#             temp_range=(cold_temp_c, max_temp),
#         )
#         db_name = os.path.basename(database)
#         logger.info(f"Database selected: {db_name}")

#         color_salt = salt_id or (salts_of_interest[0] if salts_of_interest else None)
#         results: List[Dict[str, Any]] = []

#         # Cache natural pH per CoC (Step 1 only depends on CoC, not evaluation temp)
#         natural_ph_cache: Dict[float, float] = {}

#         total = len(temp_list_c) * len(coc_list)
#         done  = 0

#         for hot_temp_c in temp_list_c:
#             for coc in coc_list:
#                 done += 1
#                 logger.info(f"[{done}/{total}] CoC={coc}, eval_temp={hot_temp_c}°C ...")

#                 # ── Step 1: natural pH at cold supply temp (cached per CoC) ──
#                 if coc not in natural_ph_cache:
#                     natural_ph = await self._step1_natural_ph(
#                         mapped_params, coc, cold_temp_c, co2_factor, database
#                     )
#                     natural_ph_cache[coc] = natural_ph
#                 else:
#                     natural_ph = natural_ph_cache[coc]

#                 # ── Step 2: SI at evaluation temp ─────────────────────────────
#                 phreeqc_result = await self._step5_hot_temp_si(
#                     mapped_params, coc, hot_temp_c, natural_ph, balance_anion, database
#                 )

#                 # Build SI detail dict + SR (Saturation Ratio = 10^SI)
#                 si_detail: Dict[str, Any] = {}
#                 for item in phreeqc_result.get("saturation_indices", []):
#                     if isinstance(item, dict):
#                         name    = item.get("mineral_name", "")
#                         si_val  = round(item.get("si_value", 0.0), 4)
#                         si_detail[name] = {
#                             "SI":               si_val,
#                             "SR":               round(10 ** si_val, 6),
#                             "log_IAP":          item.get("log_IAP"),
#                             "log_K":            item.get("log_K"),
#                             "phase":            item.get("phase"),
#                             "chemical_formula": item.get("chemical_formula"),
#                         }

#                 # Color code — per salt, 2-mode logic
#                 def _find_si_val(si_dict: Dict, target: Optional[str]) -> Optional[float]:
#                     if not target:
#                         return None
#                     if target in si_dict:
#                         return si_dict[target].get("SI")
#                     tl = target.lower()
#                     for k, v in si_dict.items():
#                         if k.lower() == tl:
#                             return v.get("SI")
#                     return None

#                 selected_si = _find_si_val(si_detail, color_salt)

#                 # Color for the primary/selected salt
#                 if selected_si is not None:
#                     color = _color_code_for_salt(
#                         selected_si, color_salt or "", inhibited_salts, thresholds
#                     )
#                 else:
#                     color = "green"

#                 # Per-salt color map (for frontend to switch views)
#                 per_salt_colors: Dict[str, str] = {}
#                 for mineral_name, mineral_data in si_detail.items():
#                     per_salt_colors[mineral_name] = _color_code_for_salt(
#                         mineral_data["SI"], mineral_name, inhibited_salts, thresholds
#                     )

#                 desc = phreeqc_result.get("description_of_solution", {})

#                 results.append({
#                     "_grid_CoC":               coc,
#                     "_grid_temp":              hot_temp_c,
#                     "_grid_pH":                natural_ph,
#                     "_cold_temp_c":            cold_temp_c,
#                     "_natural_ph_at_cold":     natural_ph,
#                     "saturation_indices":      si_detail,
#                     "description_of_solution": desc,
#                     "distribution_of_species": phreeqc_result.get("distribution_of_species", {}),
#                     "color_code":              color,           # color for selected salt
#                     "per_salt_colors":         per_salt_colors, # color for every salt
#                     "ionic_strength":          phreeqc_result.get("ionic_strength", 0.0),
#                     "charge_balance_error_pct": phreeqc_result.get("charge_balance_error_pct", 0.0),
#                     "electrical_balance":      phreeqc_result.get("electrical_balance", 0.0),
#                     "specific_conductance":    desc.get("specific_conductance"),
#                     "density":                 desc.get("density"),
#                 })

#         logger.info(f"Pipeline complete: {len(results)} grid points ({len(temp_list_c)} temps × {len(coc_list)} CoC)")
#         return results, db_name

#     # ── STEP: generate 3D graph ───────────────────────────────────────────────
#     def _generate_graph(
#         self,
#         results: List[Dict[str, Any]],
#         salt_id: Optional[str],
#         run_id: str,
#         temp_unit: str,
#     ) -> bytes:
#         display_salt = salt_id or "All Salts"

#         # Case-insensitive salt lookup helper
#         def _get_si_for_salt(si_dict: Dict, target: str) -> Optional[float]:
#             if target in si_dict:
#                 val = si_dict[target]
#                 return val.get("SI") if isinstance(val, dict) else float(val)
#             target_lower = target.lower()
#             for k, v in si_dict.items():
#                 if k.lower() == target_lower:
#                     return v.get("SI") if isinstance(v, dict) else float(v)
#             return None

#         # Filter points that have SI for the selected salt
#         if salt_id:
#             valid = [r for r in results if _get_si_for_salt(r["saturation_indices"], salt_id) is not None]
#         else:
#             valid = results

#         if not valid:
#             raise ValueError("No valid PHREEQC results to plot")

#         x_vals = np.array([r["_grid_CoC"]  for r in valid])
#         y_vals = np.array([r["_grid_temp"] for r in valid])  # °C stored

#         if salt_id:
#             z_vals = np.array([_get_si_for_salt(r["saturation_indices"], salt_id) for r in valid])
#         else:
#             # Use first available salt
#             first_salt = next(iter(valid[0]["saturation_indices"]), None)
#             z_vals = np.array([
#                 r["saturation_indices"].get(first_salt, {}).get("SI", 0.0) for r in valid
#             ])

#         colors = [
#             self.COLOUR_MAP.get(
#                 r.get("per_salt_colors", {}).get(
#                     # find exact or case-insensitive match
#                     next((k for k in r.get("per_salt_colors", {}) if k.lower() == (salt_id or "").lower()), None
#                     ) or r.get("color_code", "green"),
#                     r.get("color_code", "green")
#                 ),
#                 "#BDC3C7"
#             )
#             for r in valid
#         ]

#         # Convert temp for display label
#         y_label = "Temperature (°C)"
#         if temp_unit.upper() == "F":
#             y_display = np.array([(t * 9/5) + 32 for t in y_vals])
#             y_label = "Temperature (°F)"
#         else:
#             y_display = y_vals

#         fig = plt.figure(figsize=(13, 8), facecolor="#1A1A2E")
#         ax  = fig.add_subplot(111, projection="3d", facecolor="#16213E")

#         unique_x = sorted(set(x_vals))
#         unique_y = sorted(set(y_display))
#         dx = max(0.3, (max(unique_x) - min(unique_x)) / max(len(unique_x), 1) * 0.7) if len(unique_x) > 1 else 0.5
#         dy = max(1.5, (max(unique_y) - min(unique_y)) / max(len(unique_y), 1) * 0.7) if len(unique_y) > 1 else 5.0

#         for xi, yi, zi, color in zip(x_vals, y_display, z_vals, colors):
#             dz = abs(zi) if zi != 0 else 0.01
#             z_bottom = min(zi, 0.0)
#             ax.bar3d(xi - dx/2, yi - dy/2, z_bottom, dx, dy, dz,
#                      color=color, alpha=0.85, shade=True)

#         # SI=0 reference plane
#         if x_vals.size and y_display.size:
#             xx = np.linspace(x_vals.min() - dx, x_vals.max() + dx, 2)
#             yy = np.linspace(y_display.min() - dy, y_display.max() + dy, 2)
#             XX, YY = np.meshgrid(xx, yy)
#             ax.plot_surface(XX, YY, np.zeros_like(XX), alpha=0.12, color="white")

#         ax.set_xlabel("Cycles of Concentration", color="white", labelpad=12, fontsize=10)
#         ax.set_ylabel(y_label,                   color="white", labelpad=12, fontsize=10)
#         ax.set_zlabel(f"SI — {display_salt}",    color="white", labelpad=12, fontsize=10)
#         ax.tick_params(colors="white", labelsize=8)
#         for pane in (ax.xaxis.pane, ax.yaxis.pane, ax.zaxis.pane):
#             pane.fill = False
#             pane.set_edgecolor("#444466")
#         ax.grid(True, color="#333355", linewidth=0.4)
#         ax.set_title(f"Saturation Analysis — {display_salt}\n(Run: {run_id})",
#                      color="white", fontsize=13, fontweight="bold", pad=18)

#         from matplotlib.patches import Patch
#         ax.legend(
#             handles=[
#                 Patch(facecolor=_COLOUR_HEX["green"],  label="Protected"),
#                 Patch(facecolor=_COLOUR_HEX["yellow"], label="Caution"),
#                 Patch(facecolor=_COLOUR_HEX["red"],    label="Scale Risk"),
#             ],
#             loc="upper left", facecolor="#1A1A2E", edgecolor="#444466",
#             labelcolor="white", fontsize=9,
#         )
#         ax.view_init(elev=25, azim=225)
#         fig.tight_layout()

#         buf = io.BytesIO()
#         plt.savefig(buf, format="png", dpi=150, bbox_inches="tight",
#                     facecolor=fig.get_facecolor())
#         plt.close(fig)
#         buf.seek(0)
#         return buf.read()

#     # ── STEP: upload to S3 ───────────────────────────────────────────────────
#     def _upload_s3(self, png: bytes, run_id: str, suffix: str = "") -> str:
#         if not self.s3_bucket:
#             logger.warning("AWS_S3_BUCKET not set — skipping S3 upload")
#             return f"local://{run_id}{suffix}.png"
#         key = f"{self.s3_prefix}{run_id}{suffix}.png"
#         try:
#             s3 = self._get_s3()
#             s3.put_object(
#                 Bucket=self.s3_bucket, Key=key,
#                 Body=png, ContentType="image/png",
#             )
#             # Generate presigned URL (7 days = 604800 seconds)
#             url = s3.generate_presigned_url(
#                 "get_object",
#                 Params={"Bucket": self.s3_bucket, "Key": key},
#                 ExpiresIn=604800,
#             )
#             logger.info(f"Graph uploaded → presigned URL generated for {key}")
#             return url
#         except (BotoCoreError, ClientError) as e:
#             logger.error(f"S3 upload failed: {e} — returning placeholder URL")
#             return f"s3-upload-failed://{run_id}{suffix}.png"

#     # ── STEP: build graph_data JSON (for frontend 3D renderer) ───────────────
#     @staticmethod
#     def _build_graph_data(
#         results: List[Dict[str, Any]],
#         salt_id: Optional[str],
#         temp_unit: str,
#     ) -> Dict[str, Any]:
#         """
#         Build Plotly-ready 3D bar chart data.
#         Frontend can render this directly with Plotly or Three.js.

#         Structure:
#           - bars[]         → one entry per grid point, with x/y/z + color + click_data (ALL SI values)
#           - plotly_traces  → ready-to-use Plotly trace objects (mesh3d + hover scatter)
#           - axes           → axis labels and ranges
#           - color_map      → hex colors for green/yellow/red
#           - color_labels   → human-readable label per color
#         """
#         temp_label = f"Temperature ({'°F' if temp_unit.upper() == 'F' else '°C'})"

#         # ── Color labels (defined FIRST — used in legend + click_data below) ──
#         color_labels = {
#             "green":  "Protected (Green)",
#             "yellow": "Caution (Yellow)",
#             "red":    "Scale Risk (Red)",
#             "error":  "No Data",
#         }

#         # ── Helper: resolve SI value case-insensitively ──────────────────
#         def _get_si(si_dict: Dict, target: Optional[str]) -> Optional[float]:
#             if not target:
#                 return None
#             if target in si_dict:
#                 v = si_dict[target]
#                 return v.get("SI") if isinstance(v, dict) else float(v)
#             tl = target.lower()
#             for k, v in si_dict.items():
#                 if k.lower() == tl:
#                     return v.get("SI") if isinstance(v, dict) else float(v)
#             return None

#         # ── Build bars ───────────────────────────────────────────────────
#         bars = []
#         for r in results:
#             temp_display = round(
#                 (r["_grid_temp"] * 9/5 + 32) if temp_unit.upper() == "F" else r["_grid_temp"], 1
#             )
#             si_val = _get_si(r["saturation_indices"], salt_id)

#             # Full SI data for ALL minerals at this grid point
#             all_si = {
#                 mineral: (
#                     {
#                         "SI":               info.get("SI"),
#                         "log_IAP":          info.get("log_IAP"),
#                         "log_K":            info.get("log_K"),
#                         "chemical_formula": info.get("chemical_formula"),
#                         "phase":            info.get("phase"),
#                     }
#                     if isinstance(info, dict) else {"SI": float(info)}
#                 )
#                 for mineral, info in r["saturation_indices"].items()
#             }

#             desc = r.get("description_of_solution") or {}

#             bars.append({
#                 # ── Plotly 3D axes ──
#                 "x":         r["_grid_CoC"],   # X-axis: Cycles of Concentration
#                 "y":         si_val,            # Z-axis / bar height: SI value
#                 "z":         temp_display,      # Y-axis: Temperature
#                 # ── Color ──
#                 "color":     r["color_code"],
#                 "color_hex": _COLOUR_HEX.get(r["color_code"], "#BDC3C7"),
#                 # ── click_data: everything frontend needs when user clicks a bar ──
#                 "click_data": {
#                     "CoC":              r["_grid_CoC"],
#                     "temperature":      temp_display,
#                     "temperature_unit": "°F" if temp_unit.upper() == "F" else "°C",
#                     "pH":               r["_grid_pH"],
#                     "selected_salt":    salt_id,
#                     "SI":               si_val,
#                     "status":           color_labels.get(r["color_code"], r["color_code"]),
#                     "ionic_strength":   r.get("ionic_strength"),
#                     "charge_balance_error_pct": r.get("charge_balance_error_pct"),
#                     "density":          desc.get("density"),
#                     "activity_of_water": desc.get("activity_of_water"),
#                     # Every mineral/salt SI at this grid point
#                     "all_saturation_indices": all_si,
#                 },
#                 # ── Legacy tooltip alias (backward compat) ──
#                 "tooltip": {
#                     "CoC":              r["_grid_CoC"],
#                     "temperature":      f"{temp_display} {'°F' if temp_unit.upper() == 'F' else '°C'}",
#                     "pH":               r["_grid_pH"],
#                     "SI":               si_val,
#                     "salt":             salt_id,
#                     "ionic_strength":   r.get("ionic_strength"),
#                     "charge_balance_error_pct": r.get("charge_balance_error_pct"),
#                     "density":          desc.get("density"),
#                     "activity_of_water": desc.get("activity_of_water"),
#                     "all_saturation_indices": all_si,
#                 },
#             })

#         # ── Axis range data (defined here — BEFORE bar dimension calc below) ──
#         unique_coc  = sorted(set(b["x"] for b in bars))
#         unique_temp = sorted(set(b["z"] for b in bars))

#         # ── Build Plotly traces — true 3D bars using mesh3d ─────────────
#         # Each bar = one rectangular box (8 vertices, 12 triangles)
#         def _make_bar_mesh(x_center, z_center, y_top, color_hex, dx=0.4, dz=4.0):
#             """Create a single 3D bar as mesh3d vertices."""
#             x0, x1 = x_center - dx/2, x_center + dx/2
#             z0, z1 = z_center - dz/2, z_center + dz/2
#             y0, y1 = min(y_top, 0.0), max(y_top, 0.0)

#             # 8 corners of the box
#             vx = [x0,x1,x1,x0, x0,x1,x1,x0]
#             vy = [y0,y0,y0,y0, y1,y1,y1,y1]
#             vz = [z0,z0,z1,z1, z0,z0,z1,z1]

#             # 12 triangles (2 per face × 6 faces)
#             i = [0,0,1,1,2,2,3,3,4,4,0,0]
#             j = [1,2,2,5,3,6,0,7,5,6,4,5]
#             k = [2,3,5,6,6,7,7,4,6,7,5,1]

#             return {
#                 "type":       "mesh3d",
#                 "x": vx, "y": vy, "z": vz,
#                 "i": i, "j": j, "k": k,
#                 "color":      color_hex,
#                 "opacity":    0.85,
#                 "flatshading": True,
#                 "showscale":  False,
#                 "lighting":   {"ambient": 0.6, "diffuse": 0.8, "specular": 0.3},
#             }

#         # Bar dimensions based on grid spacing (unique_* defined above)
#         if len(unique_coc) > 1:
#             dx = (max(unique_coc) - min(unique_coc)) / len(unique_coc) * 0.7
#         else:
#             dx = 0.4

#         if len(unique_temp) > 1:
#             dz = (max(unique_temp) - min(unique_temp)) / len(unique_temp) * 0.7
#         else:
#             dz = 4.0

#         plotly_traces = []

#         # Add one invisible scatter3d per color group for the legend
#         legend_added = set()
#         for bar in bars:
#             color = bar["color"]
#             if color not in legend_added:
#                 plotly_traces.append({
#                     "type":   "scatter3d",
#                     "mode":   "markers",
#                     "name":   color_labels.get(color, color),
#                     "x":      [bar["x"]],
#                     "y":      [bar["z"]],
#                     "z":      [bar["y"] if bar["y"] is not None else 0],
#                     "marker": {"size": 0.1, "color": _COLOUR_HEX.get(color, "#BDC3C7")},
#                     "showlegend": True,
#                     "hoverinfo": "skip",
#                 })
#                 legend_added.add(color)

#         # Add mesh3d bar for each grid point
#         for bar in bars:
#             si = bar["y"] if bar["y"] is not None else 0.0
#             mesh = _make_bar_mesh(
#                 x_center=bar["x"],
#                 z_center=bar["z"],
#                 y_top=si,
#                 color_hex=_COLOUR_HEX.get(bar["color"], "#BDC3C7"),
#                 dx=dx,
#                 dz=dz,
#             )
#             # Attach to traces
#             mesh["showlegend"] = False
#             plotly_traces.append(mesh)

#             # Hover/click point at bar top — carries full click_data
#             cd = bar["click_data"]
#             plotly_traces.append({
#                 "type":       "scatter3d",
#                 "mode":       "markers",
#                 "x":          [bar["x"]],
#                 "y":          [bar["z"]],
#                 "z":          [si],
#                 "marker":     {"size": 8, "color": _COLOUR_HEX.get(bar["color"], "#BDC3C7"), "opacity": 0.01},
#                 "text":       [si],
#                 "customdata": [cd],   # full click_data attached here
#                 "hovertemplate": (
#                     f"<b>CoC:</b> {cd['CoC']}<br>"
#                     f"<b>Temp:</b> {cd['temperature']} {cd['temperature_unit']}<br>"
#                     f"<b>pH:</b> {cd['pH']}<br>"
#                     f"<b>SI ({salt_id}):</b> {si:.4f}<br>"
#                     f"<b>Status:</b> {cd['status']}"
#                     "<extra></extra>"
#                 ),
#                 "showlegend": False,
#             })

#         # ── Plotly layout ────────────────────────────────────────────────
#         x_vals = [b["x"] for b in bars]
#         z_vals = [b["z"] for b in bars]
#         y_vals = [b["y"] for b in bars if b["y"] is not None]

#         plotly_layout = {
#             "title": f"Saturation Analysis — {salt_id or 'All Salts'}",
#             "scene": {
#                 "xaxis": {
#                     "title": "Cycles of Concentration",
#                     "range": [min(x_vals) - 0.5, max(x_vals) + 0.5] if x_vals else [0, 10],
#                 },
#                 "yaxis": {
#                     "title": temp_label,
#                     "range": [min(z_vals) - 5, max(z_vals) + 5] if z_vals else [0, 200],
#                 },
#                 "zaxis": {
#                     "title": f"Saturation Index ({salt_id or 'SI'})",
#                     "range": [
#                         min(y_vals) - 0.5 if y_vals else -2,
#                         max(y_vals) + 0.5 if y_vals else 2,
#                     ],
#                 },
#                 "bgcolor": "#16213E",
#                 "xaxis_gridcolor": "#333355",
#                 "yaxis_gridcolor": "#333355",
#                 "zaxis_gridcolor": "#333355",
#             },
#             "paper_bgcolor": "#1A1A2E",
#             "font":   {"color": "white"},
#             "legend": {"bgcolor": "#1A1A2E", "bordercolor": "#444466"},
#             "margin": {"l": 0, "r": 0, "t": 40, "b": 0},
#         }

#         # (color_labels and unique_coc/unique_temp already defined above)

#         return {
#             "type":          "3d_bar",
#             "salt_id":       salt_id,
#             "temp_unit":     temp_unit,
#             "total_points":  len(bars),
#             "axes": {
#                 "x": {"label": "Cycles of Concentration", "values": unique_coc},
#                 "y": {"label": f"Saturation Index ({salt_id or 'SI'})", "unit": "SI"},
#                 "z": {"label": temp_label, "values": unique_temp},
#             },
#             "bars":           bars,
#             "plotly_traces":  plotly_traces,
#             "plotly_layout":  plotly_layout,
#             "color_map":      _COLOUR_HEX,
#             "color_labels":   color_labels,
#         }

#     # ── STEP: enrich each grid point with all calculated values ─────────────
#     @staticmethod
#     async def _enrich_grid_points(
#         results: List[Dict[str, Any]],
#         base_water_parameters: Dict[str, Any],
#         req: Dict[str, Any],
#     ) -> List[Dict[str, Any]]:
#         """
#         For each grid point, calculate:
#           - Deposition indices (LSI, RSI, PSI, Larson-Skold, Stiff & Davis, CCPP)
#           - Blowdown & Makeup rates
#           - Chemical feedrate & cost
#           - Corrosion rates (per metal in asset_info.systemMetallurgy)
#         """
#         calc_svc = CalculationService()
#         ct_svc   = CoolingTowerService()

#         asset_info       = req.get("asset_info") or {}
#         raw_mat          = req.get("raw_material_chemistry") or {}
#         product_blend    = req.get("product_blend") or {}
#         dosage_ppm       = float(req.get("dosage_ppm") or 2.0)
#         temp_unit        = req.get("temp_unit", "C")

#         # Cooling tower params from asset_info
#         recirc_rate_gpm  = float(asset_info.get("recirculationRate") or 0)
#         hot_temp_f       = float(asset_info.get("hotWaterTempF") or 0)
#         cold_temp_f      = float(asset_info.get("coldWaterTempF") or 0)
#         wet_bulb_f       = float(asset_info.get("wetBulbTempF") or 0)
#         drift_pct        = float(asset_info.get("driftPercent") or 0.1)
#         evap_factor      = float(asset_info.get("evaporationFactorPercent") or 85.0)
#         metallurgy       = asset_info.get("systemMetallurgy") or []

#         # Product cost ($/lb or $/kg)
#         product_cost_per_lb = float(product_blend.get("costPerLb") or 0)
#         product_name        = product_blend.get("productName") or "Product"

#         enriched = []
#         for r in results:
#             coc      = r["_grid_CoC"]
#             temp_c   = r["_grid_temp"]   # always °C internally
#             ph       = r["_grid_pH"]
#             ionic_s  = r.get("ionic_strength", 0.0)

#             # Build concentrated water params for this grid point
#             conc_params: Dict[str, Any] = {}
#             for key, val in base_water_parameters.items():
#                 if isinstance(val, dict):
#                     raw_val = val.get("value", 0)
#                     unit    = val.get("unit", "mg/L")
#                 else:
#                     raw_val = val
#                     unit    = "mg/L"
#                 try:
#                     numeric = float(raw_val)
#                 except (TypeError, ValueError):
#                     numeric = 0.0
#                 # pH and Temperature don't scale with CoC
#                 if key.lower() in ("ph", "temperature", "temp"):
#                     conc_params[key] = {"value": numeric, "unit": unit}
#                 else:
#                     conc_params[key] = {"value": round(numeric * coc, 4), "unit": unit}

#             # Override pH and Temperature with grid values
#             conc_params["pH"]          = {"value": ph,     "unit": ""}
#             conc_params["Temperature"] = {"value": temp_c, "unit": "C"}

#             # ── Deposition Indices — use PHREEQC SI values directly ─────────
#             # Extract key SI values from PHREEQC output
#             def _get_si_val(name: str) -> Optional[float]:
#                 for k, v in r["saturation_indices"].items():
#                     if k.lower() == name.lower():
#                         return v.get("SI") if isinstance(v, dict) else float(v)
#                 return None

#             calcite_si  = _get_si_val("Calcite")
#             gypsum_si   = _get_si_val("Gypsum")
#             dolomite_si = _get_si_val("Dolomite")
#             anhydrite_si= _get_si_val("Anhydrite")

#             indices: Dict[str, Any] = {}

#             # LSI — directly from PHREEQC Calcite SI
#             if calcite_si is not None:
#                 lsi_val = round(calcite_si, 3)
#                 if lsi_val > 0.5:
#                     lsi_interp, lsi_risk = "Scaling Tendency", "Scale Forming"
#                 elif lsi_val > 0:
#                     lsi_interp, lsi_risk = "Slight Scaling Tendency", "Low Scale Risk"
#                 elif lsi_val >= -0.5:
#                     lsi_interp, lsi_risk = "Slightly Corrosive", "Low Corrosion"
#                 else:
#                     lsi_interp, lsi_risk = "Corrosive", "Corrosive"
#                 indices["lsi"] = {
#                     "lsi": lsi_val, "pH_actual": ph,
#                     "interpretation": lsi_interp, "risk": lsi_risk,
#                     "source": "PHREEQC Calcite SI",
#                 }
#             else:
#                 try:
#                     indices["lsi"] = await calc_svc.calculate_lsi(conc_params)
#                 except Exception as e:
#                     indices["lsi"] = {"error": str(e)}

#             # RSI (Ryznar) = pH_actual - 2×LSI  (derived from PHREEQC LSI)
#             if calcite_si is not None:
#                 lsi_val = calcite_si
#                 rsi_val = round(ph - 2 * lsi_val, 3)
#                 if rsi_val < 5.5:
#                     rsi_interp, rsi_risk = "Heavy Scaling", "High Scale Risk"
#                 elif rsi_val < 6.2:
#                     rsi_interp, rsi_risk = "Moderate Scaling", "Moderate Scale Risk"
#                 elif rsi_val < 7.0:
#                     rsi_interp, rsi_risk = "Slight Scaling", "Low Scale Risk"
#                 elif rsi_val < 7.5:
#                     rsi_interp, rsi_risk = "Balanced", "Balanced"
#                 elif rsi_val < 9.0:
#                     rsi_interp, rsi_risk = "Slight Corrosion", "Low Corrosion"
#                 else:
#                     rsi_interp, rsi_risk = "Heavy Corrosion", "High Corrosion"
#                 indices["ryznar"] = {
#                     "ri": rsi_val, "pH_actual": ph,
#                     "interpretation": rsi_interp, "risk": rsi_risk,
#                     "source": "Derived from PHREEQC Calcite SI",
#                 }
#             else:
#                 try:
#                     indices["ryznar"] = await calc_svc.calculate_ryznar(conc_params)
#                 except Exception as e:
#                     indices["ryznar"] = {"error": str(e)}

#             # PSI (Puckorius) — calculated from conc_params
#             try:
#                 indices["puckorius"] = await calc_svc.calculate_puckorius(conc_params)
#             except Exception as e:
#                 indices["puckorius"] = {"error": str(e)}

#             # Larson-Skold — from conc_params (Cl, SO4, HCO3)
#             try:
#                 indices["larson_skold"] = await calc_svc.calculate_larson_skold(conc_params)
#             except Exception as e:
#                 indices["larson_skold"] = {"error": str(e)}

#             # Stiff & Davis — from conc_params + ionic strength
#             try:
#                 indices["stiff_davis"] = await calc_svc.calculate_stiff_davis(conc_params, ionic_s)
#             except Exception as e:
#                 indices["stiff_davis"] = {"error": str(e)}

#             # CCPP — from Calcite SI (PHREEQC)
#             # CCPP (mg/L as CaCO3) ≈ Calcite SI × 50 × [Ca²⁺] correction
#             # More accurate: use equilibrium phases if available
#             eq_phases = r.get("equilibrium_phases", {})
#             calcite_moles = eq_phases.get("Calcite")
#             if calcite_moles is not None:
#                 ccpp_ppm = round(calcite_moles * 100.09 * 1000, 2)
#             elif calcite_si is not None:
#                 # Approximate: CCPP ≈ SI × Ca_conc_as_CaCO3 / 10
#                 ca_val = 0.0
#                 for k, v in base_water_parameters.items():
#                     if k.lower() in ("calcium", "ca"):
#                         ca_val = float(v.get("value", 0) if isinstance(v, dict) else v) * coc
#                         break
#                 ca_as_caco3 = ca_val * (100.09 / 40.08)
#                 ccpp_ppm = round(calcite_si * ca_as_caco3 / 10, 2)
#             else:
#                 ccpp_ppm = None

#             if ccpp_ppm is not None:
#                 if ccpp_ppm > 15:
#                     ccpp_interp, ccpp_risk = "Heavy Scale Forming", "High Scale Risk"
#                 elif ccpp_ppm > 0:
#                     ccpp_interp, ccpp_risk = "Slight Scale Forming", "Moderate Scale Risk"
#                 elif ccpp_ppm >= -15:
#                     ccpp_interp, ccpp_risk = "Slight Dissolution", "Low Corrosion"
#                 else:
#                     ccpp_interp, ccpp_risk = "Corrosive", "Corrosive"
#                 indices["ccpp"] = {
#                     "ccpp_ppm": ccpp_ppm,
#                     "interpretation": ccpp_interp,
#                     "risk": ccpp_risk,
#                     "source": "PHREEQC equilibrium phases" if calcite_moles is not None else "Estimated from Calcite SI",
#                 }
#             else:
#                 indices["ccpp"] = {"ccpp_ppm": None, "interpretation": "N/A", "risk": "N/A"}

#             # ── Cooling Tower Water Balance ─────────────────────────────────
#             water_balance: Dict[str, Any] = {}
#             if recirc_rate_gpm > 0 and hot_temp_f > 0 and cold_temp_f > 0:
#                 try:
#                     wb = await ct_svc.calculate_tower_water_balance(
#                         recirculation_rate_gpm=recirc_rate_gpm,
#                         hot_water_temp_f=hot_temp_f,
#                         cold_water_temp_f=cold_temp_f,
#                         wet_bulb_temp_f=wet_bulb_f or (cold_temp_f - 10),
#                         coc=coc,
#                         drift_percent=drift_pct,
#                         evaporation_factor_percent=evap_factor,
#                     )
#                     water_balance = {
#                         "blowdown_rate_gpm":  wb["blowdown"]["blowdown_rate_gpm"],
#                         "makeup_rate_gpm":    wb["makeup"]["makeup_rate_gpm"],
#                         "evaporation_gpm":    wb["evaporation"]["evaporation_rate_gpm"],
#                         "range_f":            wb["range"]["range_f"],
#                         "approach_f":         wb["approach"]["approach_f"],
#                         "efficiency_pct":     wb["efficiency"]["efficiency_percent"],
#                         "heat_load_btu_hr":   wb["heat_load"]["heat_load_btu_hr"],
#                         "cooling_tons":       wb["cooling_tons"]["cooling_tons"],
#                     }
#                 except Exception as e:
#                     logger.warning(f"Water balance failed for CoC={coc}: {e}")
#                     water_balance = {"error": str(e)}
#             else:
#                 water_balance = {"note": "Provide asset_info with recirculationRate, hotWaterTempF, coldWaterTempF"}

#             # ── Chemical Feedrate & Cost ────────────────────────────────────
#             chemical_data: Dict[str, Any] = {}
#             bd_gpm = water_balance.get("blowdown_rate_gpm") if isinstance(water_balance.get("blowdown_rate_gpm"), (int, float)) else None
#             if bd_gpm and bd_gpm > 0 and dosage_ppm > 0:
#                 try:
#                     day_result  = await ct_svc.calculate_chemical_required_per_day(dosage_ppm, bd_gpm)
#                     lbs_per_day = day_result["chemical_lbs_per_day"]
#                     kg_per_day  = round(lbs_per_day * 0.453592, 3)
#                     kg_per_year = round(kg_per_day * 350, 1)
#                     lbs_per_year = round(lbs_per_day * 350, 1)
#                     chemical_data = {
#                         "product_name":   product_name,
#                         "dosage_ppm":     dosage_ppm,
#                         "lbs_per_day":    lbs_per_day,
#                         "kg_per_day":     kg_per_day,
#                         "lbs_per_year":   lbs_per_year,
#                         "kg_per_year":    kg_per_year,
#                     }
#                     if product_cost_per_lb > 0:
#                         cost_result = await ct_svc.calculate_chemical_cost(dosage_ppm, product_cost_per_lb)
#                         chemical_data["cost_per_million_lbs_bd"] = cost_result["cost_per_million_lbs_bd"]
#                         chemical_data["annual_cost_usd"] = round(lbs_per_year * product_cost_per_lb, 2)
#                 except Exception as e:
#                     logger.warning(f"Chemical feedrate failed: {e}")
#                     chemical_data = {"error": str(e)}
#             else:
#                 chemical_data = {"note": "Provide asset_info.recirculationRate and dosage_ppm for feedrate"}

#             # ── Corrosion Rates ─────────────────────────────────────────────
#             corrosion: Dict[str, Any] = {}
#             si_dict_flat = {
#                 k: (v.get("SI") if isinstance(v, dict) else float(v))
#                 for k, v in r["saturation_indices"].items()
#             }
#             # DO estimate: Henry's law approximation for open cooling water
#             do_ppm = max(0.0, round(14.62 - 0.3898 * temp_c + 0.006969 * temp_c**2 - 0.00005896 * temp_c**3, 2))

#             # Always calculate for standard metals, plus any in metallurgy list
#             metals_to_calc = list(set(["mild_steel", "copper", "admiralty_brass"] + [
#                 m.lower().replace(" ", "_").replace("-", "_") for m in metallurgy
#             ]))

#             for metal_key in metals_to_calc:
#                 try:
#                     if "mild_steel" in metal_key or "steel" in metal_key:
#                         result_cr = await calc_svc.calculate_mild_steel_corrosion(
#                             conc_params, si_dict_flat, do_ppm, temp_c
#                         )
#                         corrosion["mild_steel"] = {**result_cr, "do_ppm_used": do_ppm}
#                     elif "copper" in metal_key:
#                         result_cr = await calc_svc.calculate_copper_corrosion(
#                             conc_params, si_dict_flat, do_ppm, temp_c, ph
#                         )
#                         corrosion["copper"] = {**result_cr, "do_ppm_used": do_ppm}
#                     elif "admiralty" in metal_key or "brass" in metal_key:
#                         result_cr = await calc_svc.calculate_copper_corrosion(
#                             conc_params, si_dict_flat, do_ppm, temp_c, ph
#                         )
#                         cr_adj = round(result_cr["cr_mpy"] * 0.85, 2)
#                         corrosion["admiralty_brass"] = {**result_cr, "cr_mpy": cr_adj, "do_ppm_used": do_ppm}
#                 except Exception as e:
#                     logger.warning(f"Corrosion calc failed for {metal_key}: {e}")
#                     corrosion[metal_key] = {"error": str(e)}

#             # ── Merge into result ───────────────────────────────────────────
#             enriched.append({
#                 **r,
#                 "indices":       indices,
#                 "water_balance": water_balance,
#                 "chemical":      chemical_data,
#                 "corrosion":     corrosion,
#             })

#         return enriched

#     # ── STEP: build interactive chart data (no image, no S3) ────────────────
#     @staticmethod
#     def _build_chart_data(
#         results: List[Dict[str, Any]],
#         salt_id: Optional[str],
#         temp_unit: str,
#     ) -> Dict[str, Any]:
#         """
#         Build frontend-ready structured data for interactive 3D bar chart.
#         Frontend (React/Plotly/Three.js) renders this directly.

#         Each point contains:
#           - coc, temperature, ph  → axis values
#           - si                    → bar height (selected salt SI)
#           - color                 → green / yellow / red
#           - all_si                → every mineral SI at this grid point (for hover panel)
#           - ionic_strength, charge_balance_error_pct, activity_of_water
#         """
#         temp_suffix = "°F" if temp_unit.upper() == "F" else "°C"

#         def _get_si(si_dict: Dict, target: Optional[str]) -> Optional[float]:
#             if not target:
#                 return None
#             if target in si_dict:
#                 v = si_dict[target]
#                 return v.get("SI") if isinstance(v, dict) else float(v)
#             tl = target.lower()
#             for k, v in si_dict.items():
#                 if k.lower() == tl:
#                     return v.get("SI") if isinstance(v, dict) else float(v)
#             return None

#         points = []
#         for r in results:
#             temp_display = round(
#                 (r["_grid_temp"] * 9/5 + 32) if temp_unit.upper() == "F" else r["_grid_temp"], 2
#             )
#             si_val = _get_si(r["saturation_indices"], salt_id)
#             desc   = r.get("description_of_solution") or {}

#             # All minerals at this grid point
#             all_si = {
#                 mineral: {
#                     "SI":               info.get("SI") if isinstance(info, dict) else float(info),
#                     "log_IAP":          info.get("log_IAP") if isinstance(info, dict) else None,
#                     "log_K":            info.get("log_K") if isinstance(info, dict) else None,
#                     "chemical_formula": info.get("chemical_formula") if isinstance(info, dict) else None,
#                 }
#                 for mineral, info in r["saturation_indices"].items()
#             }

#             points.append({
#                 # ── Axis values ──
#                 "coc":         r["_grid_CoC"],
#                 "temperature": temp_display,
#                 "ph":          r["_grid_pH"],
#                 # ── Bar height ──
#                 "si":          si_val,
#                 # ── Color coding ──
#                 "color":       r["color_code"],
#                 "color_hex":   _COLOUR_HEX.get(r["color_code"], "#BDC3C7"),
#                 # ── Solution properties ──
#                 "ionic_strength":            r.get("ionic_strength"),
#                 "charge_balance_error_pct":  r.get("charge_balance_error_pct"),
#                 "activity_of_water":         desc.get("activity_of_water"),
#                 # ── All mineral SI values (for hover/click panel) ──
#                 "all_si": all_si,
#                 # ── Enriched calculations (from _enrich_grid_points) ──
#                 "indices":       r.get("indices", {}),
#                 "water_balance": r.get("water_balance", {}),
#                 "chemical":      r.get("chemical", {}),
#                 "corrosion":     r.get("corrosion", {}),
#                 # ── Description of solution (full PHREEQC output) ──
#                 "description_of_solution": desc,
#                 "distribution_of_species": r.get("distribution_of_species", {}),
#                 "electrical_balance":      r.get("electrical_balance", 0.0),
#             })

#         # Unique axis values (for frontend axis tick generation)
#         unique_coc  = sorted(set(p["coc"]         for p in points))
#         unique_temp = sorted(set(p["temperature"] for p in points))
#         unique_ph   = sorted(set(p["ph"]          for p in points))

#         color_labels = {
#             "green":  "Protected",
#             "yellow": "Caution",
#             "red":    "Scale Risk",
#             "error":  "No Data",
#         }

#         return {
#             "salt_id":    salt_id,
#             "temp_unit":  temp_suffix,
#             "axes": {
#                 "x": {"label": "Cycles of Concentration", "values": unique_coc},
#                 "y": {"label": f"Temperature ({temp_suffix})",  "values": unique_temp},
#                 "z": {"label": f"Saturation Index ({salt_id or 'SI'})", "unit": "SI"},
#             },
#             "color_map":    _COLOUR_HEX,
#             "color_labels": color_labels,
#             "total_points": len(points),
#             "available_salts": sorted(set(
#                 mineral
#                 for p in points
#                 for mineral in (p.get("all_si") or {}).keys()
#             )),
#             "points":       points,
#         }

#     # ── STEP: summary counts ─────────────────────────────────────────────────
#     @staticmethod
#     def _summary(results: List[Dict]) -> Dict[str, int]:
#         counts: Dict[str, int] = {"green": 0, "yellow": 0, "red": 0, "error": 0}
#         for r in results:
#             counts[r.get("color_code", "error")] = counts.get(r.get("color_code", "error"), 0) + 1
#         return counts

#     # ─────────────────────────────────────────────────────────────────────────
#     # ADDITIONAL CALCULATIONS PER GRID POINT
#     # ─────────────────────────────────────────────────────────────────────────
#     async def _add_calculations_to_results(
#         self,
#         results: List[Dict[str, Any]],
#         raw_water: Dict[str, Any],
#     ) -> List[Dict[str, Any]]:
#         """
#         For each grid point, calculate:
#           - LSI, RSI (Ryznar), PSI (Puckorius)
#           - CCPP
#           - Mild Steel Corrosion Rate
#         Uses the grid point's pH, temp, ionic_strength + base water params.
#         """
#         try:
#             from app.services.calculation_service import CalculationService
#             calc = CalculationService()
#         except Exception as e:
#             logger.warning(f"CalculationService unavailable: {e}")
#             return results

#         for r in results:
#             try:
#                 # Build parameters dict for this grid point
#                 # Use base water params + override pH and Temperature from grid
#                 params: Dict[str, Any] = {}
#                 for k, v in raw_water.items():
#                     params[k] = v

#                 # Override with grid point values
#                 params["pH"]          = {"value": r["_grid_pH"],   "unit": ""}
#                 params["Temperature"] = {"value": r["_grid_temp"],  "unit": "°C"}

#                 # Build phreeqc_output dict for CCPP
#                 phreeqc_output = {
#                     "ionic_strength":     r.get("ionic_strength", 0.0),
#                     "saturation_indices": [
#                         {"mineral_name": k, "si_value": v.get("SI", 0.0)}
#                         for k, v in r.get("saturation_indices", {}).items()
#                     ],
#                 }

#                 ionic_strength = r.get("ionic_strength", 0.0)

#                 # Run calculations
#                 calcs: Dict[str, Any] = {}

#                 try:
#                     calcs["lsi"] = await calc.calculate_lsi(params)
#                 except Exception:
#                     pass

#                 try:
#                     calcs["ryznar"] = await calc.calculate_ryznar(params)
#                 except Exception:
#                     pass

#                 try:
#                     calcs["puckorius"] = await calc.calculate_puckorius(params)
#                 except Exception:
#                     pass

#                 try:
#                     calcs["ccpp"] = await calc.calculate_ccpp(phreeqc_output)
#                 except Exception:
#                     pass

#                 try:
#                     calcs["larson_skold"] = await calc.calculate_larson_skold(params)
#                 except Exception:
#                     pass

#                 try:
#                     sat_indices_dict = {
#                         item["mineral_name"]: item["si_value"]
#                         for item in phreeqc_output["saturation_indices"]
#                     }
#                     calcs["mild_steel_corrosion"] = await calc.calculate_mild_steel_corrosion(
#                         params, sat_indices_dict, do_ppm=5.0,
#                         temp_c=r["_grid_temp"]
#                     )
#                 except Exception:
#                     pass

#                 r["calculations"] = calcs

#             except Exception as e:
#                 logger.warning(f"Calculations failed for CoC={r.get('_grid_CoC')}: {e}")
#                 r["calculations"] = {}

#         return results

#     # ─────────────────────────────────────────────────────────────────────────
#     # PUBLIC: run_analysis
#     # ─────────────────────────────────────────────────────────────────────────
#     async def run_analysis(self, req: Dict[str, Any]) -> Dict[str, Any]:
#         run_id = str(uuid.uuid4())
#         logger.info(f"Saturation run started  run_id={run_id}")

#         # ── 1. Map dynamic water params ───────────────────────────────────────
#         raw_water = req.get("base_water_parameters", {})
#         mapped    = _map_water_params(raw_water)
#         if not mapped:
#             raise ValueError("base_water_parameters could not be mapped to any known ions")

#         base_ph = float(_get_ion_value(mapped, "pH") or 7.0)

#         # ── 2. pH adjustment chemical ─────────────────────────────────────────
#         mapped = _apply_ph_adjustment(mapped, req.get("adjustment_chemical"))

#         # ── 3. Thresholds from raw_material_chemistry ─────────────────────────
#         dosage_ppm = float(req.get("dosage_ppm") or 2.0)
#         thresholds = _parse_thresholds(req.get("raw_material_chemistry"), dosage_ppm)

#         # ── 4. Resolve temperatures ───────────────────────────────────────────
#         asset_info = req.get("asset_info") or {}

#         # Cold basin temp (Step 1-3) — from asset supplyTemperature or temp_min
#         cold_temp_raw  = asset_info.get("supplyTemperature") or req.get("temp_min") or 32.2
#         cold_temp_unit = asset_info.get("supplyTemperatureType") or req.get("temp_unit") or "°F"
#         cold_temp_c    = _to_celsius(float(cold_temp_raw), cold_temp_unit)

#         # Hot evaluation temp (Step 5-6) — from asset returnTemperature or temp_max
#         hot_temp_raw   = asset_info.get("returnTemperature") or req.get("temp_max") or 55.0
#         hot_temp_unit  = asset_info.get("returnTemperatureType") or req.get("temp_unit") or "°F"
#         hot_temp_c     = _to_celsius(float(hot_temp_raw), hot_temp_unit)

#         # Sanity check: hot temp must be > cold temp
#         # If inverted, swap them (common data entry error)
#         if hot_temp_c < cold_temp_c:
#             logger.warning(
#                 f"Hot temp ({hot_temp_c}°C) < cold temp ({cold_temp_c}°C) — "
#                 f"likely unit mismatch. Swapping."
#             )
#             cold_temp_c, hot_temp_c = hot_temp_c, cold_temp_c

#         logger.info(f"Temperatures: cold={cold_temp_c}°C, hot={hot_temp_c}°C")

#         # ── 5. CO2 factor ─────────────────────────────────────────────────────
#         approach_to_wb = asset_info.get("approachToWB")
#         if approach_to_wb is None:
#             # Estimate: cold supply temp - wet bulb (assume 5-10°F range if unknown)
#             approach_to_wb = 7.0

#         co2_factor = _calculate_co2_factor(
#             system_type    = asset_info.get("type") or asset_info.get("systemType"),
#             tower_type     = asset_info.get("towerType"),
#             fill_type      = asset_info.get("fillType"),
#             draft_type     = asset_info.get("draftType"),
#             approach_to_wb = float(approach_to_wb),
#             co2_override   = req.get("co2_log_partial_pressure"),
#         )
#         logger.info(f"CO2 factor: {co2_factor}")

#         # ── 6. Build CoC list ─────────────────────────────────────────────────
#         coc_min      = float(req.get("coc_min") or 1.0)
#         coc_max      = float(req.get("coc_max") or 10.0)
#         coc_interval = float(req.get("coc_interval") or 1.0)
#         coc_list     = self._build_coc_list(coc_min, coc_max, coc_interval)
#         logger.info(f"CoC list: {coc_list}")

#         # ── 7. Build evaluation temperature list ──────────────────────────────
#         # Client: Do CurrentTemp = temp_min to temp_max (step temp_interval)
#         temp_unit = req.get("temp_unit", "F")
#         temp_min_raw  = float(req.get("temp_min") or 110.0)
#         temp_max_raw  = float(req.get("temp_max") or 160.0)
#         temp_interval = float(req.get("temp_interval") or 10.0)

#         # Build temp list in °C
#         temp_list_c: List[float] = []
#         t = temp_min_raw
#         while t <= temp_max_raw + 1e-9:
#             temp_list_c.append(_to_celsius(t, temp_unit))
#             t += max(temp_interval, 0.1)

#         if not temp_list_c:
#             temp_list_c = [hot_temp_c]  # fallback to asset return temp

#         logger.info(f"Eval temp list (°C): {temp_list_c}")
#         logger.info(f"Grid: {len(coc_list)} CoC × {len(temp_list_c)} Temp = {len(coc_list)*len(temp_list_c)} points")

#         # ── 8. Run 2-step PHREEQC pipeline (Temp × CoC grid) ─────────────────
#         salt_id           = req.get("salt_id")
#         salts_of_interest = req.get("salts_of_interest")
#         inhibited_salts   = _get_inhibited_salts(req.get("raw_material_chemistry"))
#         logger.info(f"Inhibited salts: {inhibited_salts}")

#         results, db_used = await self._run_two_step_pipeline(
#             mapped_params     = mapped,
#             coc_list          = coc_list,
#             cold_temp_c       = cold_temp_c,
#             temp_list_c       = temp_list_c,
#             co2_factor        = co2_factor,
#             salt_id           = salt_id,
#             salts_of_interest = salts_of_interest,
#             thresholds        = thresholds,
#             inhibited_salts   = inhibited_salts,
#             balance_cation    = req.get("balance_cation", "Na"),
#             balance_anion     = req.get("balance_anion", "Cl"),
#         )

#         # ── 9. Add additional calculations per grid point ─────────────────────
#         results = await self._add_calculations_to_results(results, raw_water)

#         # ── 10. Resolve effective salt (case-insensitive) ─────────────────────
#         effective_salt = salt_id
#         if results:
#             sample_si = results[0].get("saturation_indices", {})
#             available = list(sample_si.keys())
#             logger.info(f"PHREEQC returned {len(available)} minerals: {available[:15]}")

#             if salt_id:
#                 found = any(k.lower() == salt_id.lower() for k in available)
#                 if not found:
#                     logger.warning(f"salt_id '{salt_id}' not found. Available: {available[:10]}. Using first.")
#                     effective_salt = available[0] if available else None
#                 else:
#                     effective_salt = next(k for k in available if k.lower() == salt_id.lower())
#             else:
#                 effective_salt = available[0] if available else None
#         temp_unit = req.get("temp_unit", "F")
#         graph_url = "not-generated"
#         try:
#             png       = self._generate_graph(results, effective_salt, run_id, temp_unit)
#             graph_url = self._upload_s3(png, run_id)
#         except Exception as e:
#             logger.warning(f"Graph generation/upload failed (non-fatal): {e}")

#         # ── 10. Build Plotly-ready graph_data ─────────────────────────────────
#         graph_data = self._build_graph_data(results, effective_salt, temp_unit)

#         # ── 11. Summary ───────────────────────────────────────────────────────
#         summary = self._summary(results)

#         # ── 12. Save to DB ────────────────────────────────────────────────────
#         doc = {
#             "run_id":                  run_id,
#             "salt_id":                 effective_salt,
#             "salts_of_interest":       salts_of_interest,
#             "dosage_ppm":              float(req.get("dosage_ppm") or 2.0),
#             "coc_min":                 coc_min,
#             "coc_max":                 coc_max,
#             "coc_interval":            coc_interval,
#             "cold_basin_temp_c":       cold_temp_c,
#             "hot_basin_temp_c":        hot_temp_c,
#             "temp_unit":               temp_unit,
#             "ph_mode":                 req.get("ph_mode", "natural"),
#             "co2_factor":              co2_factor,
#             "adjustment_chemical":     req.get("adjustment_chemical"),
#             "balance_cation":          req.get("balance_cation", "Na"),
#             "balance_anion":           req.get("balance_anion", "Cl"),
#             "database_used":           db_used,
#             "total_grid_points":       len(results),
#             "grid_results":            results,
#             "graph_url":               graph_url,
#             "graph_data":              graph_data,
#             "summary":                 summary,
#             "thresholds":              thresholds,
#             "base_water_parameters":   raw_water,
#             "product_blend":           req.get("product_blend"),
#             "raw_material_chemistry":  req.get("raw_material_chemistry"),
#             "asset_info":              asset_info,
#             "created_at":              datetime.now(timezone.utc).isoformat(),
#         }
#         await db.db["saturation_runs"].insert_one(doc)
#         logger.info(f"Saturation run saved  run_id={run_id}  summary={summary}")

#         return {k: v for k, v in doc.items() if k != "_id"}

#     # ─────────────────────────────────────────────────────────────────────────
#     # PUBLIC: switch_salt  (re-graph without PHREEQC re-run)
#     # ─────────────────────────────────────────────────────────────────────────
#     async def switch_salt(self, run_id: str, salt_id: str) -> Dict[str, Any]:
#         doc = await db.db["saturation_runs"].find_one({"run_id": run_id})
#         if not doc:
#             raise ValueError(f"Run not found: {run_id}")

#         results    = doc["grid_results"]
#         temp_unit  = doc.get("temp_unit", "F")
#         thresholds = doc.get("thresholds", {"max_si_at_dose": 0.0, "band_lower": 0.0, "band_upper": 0.5})

#         if not results:
#             raise ValueError(f"No grid results saved for run_id: {run_id}")

#         # Find actual mineral name (case-insensitive) from saved results
#         sample_si    = results[0].get("saturation_indices", {})
#         available    = list(sample_si.keys())
#         salt_id_lower = salt_id.lower()

#         # Resolve exact key as stored in DB
#         resolved_salt = None
#         for k in available:
#             if k.lower() == salt_id_lower:
#                 resolved_salt = k
#                 break

#         if resolved_salt is None:
#             raise ValueError(
#                 f"Salt '{salt_id}' not found in saved results. "
#                 f"Available salts: {available[:20]}"
#             )

#         # Re-color for resolved salt (case-insensitive safe)
#         for r in results:
#             si_info = r["saturation_indices"].get(resolved_salt)
#             if si_info is not None:
#                 si_val = si_info.get("SI", si_info) if isinstance(si_info, dict) else float(si_info)
#                 r["color_code"] = _color_code(
#                     float(si_val),
#                     thresholds["max_si_at_dose"],
#                     thresholds["band_lower"],
#                     thresholds["band_upper"],
#                 )
#             else:
#                 r["color_code"] = "error"

#         # Build interactive chart data for new salt
#         chart_data = self._build_chart_data(results, resolved_salt, temp_unit)
#         summary    = self._summary(results)

#         # Update DB
#         await db.db["saturation_runs"].update_one(
#             {"run_id": run_id},
#             {"$set": {
#                 "active_salt_id": resolved_salt,
#                 "chart_data":     chart_data,
#                 "summary":        summary,
#             }},
#         )

#         return {
#             "run_id":     run_id,
#             "salt_id":    resolved_salt,
#             "chart_data": chart_data,
#             "summary":    summary,
#         }

#     # ─────────────────────────────────────────────────────────────────────────
#     # PUBLIC: get_available_salts  (PHREEQC mineral list, cached in MongoDB)
#     # ─────────────────────────────────────────────────────────────────────────
#     async def get_available_salts(self) -> List[Dict[str, str]]:
#         # Try cache first — use a versioned key so old incomplete caches are ignored
#         cached = await db.get_cached_phreeqc_info("default_v2")
#         if cached and cached.get("minerals"):
#             return cached["minerals"]

#         # Parse all minerals from .dat file (or fallback to PHREEQC run)
#         salts = await self._fetch_salts_from_phreeqc()

#         # Cache result under versioned key
#         await db.cache_phreeqc_database_info("default_v2", {"minerals": salts})
#         return salts

#     async def _fetch_salts_from_phreeqc(self) -> List[Dict[str, str]]:
#         """
#         Fetch ALL minerals/salts from the PHREEQC database.

#         Strategy (in order):
#           1. Parse PHASES section directly from phreeqc.dat  ← returns every mineral
#           2. If that yields nothing, also try pitzer.dat
#           3. Fallback: run a minimal PHREEQC simulation and collect SI output
#              (legacy behaviour — only returns minerals relevant to that water chemistry)
#         """
#         # ── Primary: parse .dat file directly ────────────────────────────────
#         salts = self.phreeqc.parse_phases_from_dat_file(self.phreeqc.phreeqc_dat)

#         if not salts:
#             # Try pitzer.dat as well (may have additional minerals)
#             logger.info("phreeqc.dat yielded no minerals — trying pitzer.dat")
#             salts = self.phreeqc.parse_phases_from_dat_file(self.phreeqc.pitzer_dat)

#         if salts:
#             logger.info(f"✅ Fetched {len(salts)} salts by parsing PHASES section from .dat file")
#             return salts

#         # ── Fallback: run minimal PHREEQC simulation ─────────────────────────
#         logger.warning(
#             "Direct .dat PHASES parse returned no results — "
#             "falling back to PHREEQC simulation (may return incomplete salt list)"
#         )
#         minimal_params = {
#             "pH": 7.0, "Temperature": 25.0,
#             "Ca": 100.0, "Mg": 30.0, "Na": 50.0, "K": 5.0,
#             "HCO3": 150.0, "SO4": 50.0, "Cl": 50.0, "SiO2": 20.0,
#             # Include trace ions so more minerals appear in SI output
#             "Ba": 0.1, "Sr": 0.1, "Fe": 0.1, "F": 0.1,
#         }
#         try:
#             result = await self.phreeqc._run_phreeqc_single(minimal_params, self.phreeqc.phreeqc_dat)
#             salts = []
#             for item in result.get("saturation_indices", []):
#                 if isinstance(item, dict):
#                     salts.append({
#                         "name":             item.get("mineral_name", ""),
#                         "chemical_formula": item.get("chemical_formula", ""),
#                         "phase":            item.get("phase", ""),
#                     })
#             logger.info(f"Fallback PHREEQC run returned {len(salts)} salts")
#             return salts
#         except Exception as e:
#             logger.error(f"Failed to fetch salts from PHREEQC fallback run: {e}")
#             return []







#####################################################


"""
Saturation Analysis Service  — v4
===================================
Implements client's exact 2-step PHREEQC workflow:

  Step 1-3  (per CoC):
    SOLUTION at cold basin temp + EQUILIBRIUM_PHASES CO2(g)
    → Calculates natural pH after CO2 degassing

  Step 5-6  (per CoC):
    SOLUTION at hot evaluation temp, pH from Step 3, Cl charge balance
    → Final SI values used for graph and display

CO2 partial pressure is auto-calculated from tower type:
  Base -3.4 + airflow + fill + draft + approach_to_WB adjustments

Special cases:
  Evaporative Condenser → base -3.4, no correction
  Once Through Cooling  → no EQUILIBRIUM_PHASES at all

pH Mode:
  natural → pH derived from CO2 equilibration (Step 1-3)
  fixed   → user-supplied pH, CO2 equilibration skipped

Adjustment Chemical (HCl / H2SO4 / NaOH):
  Used ONLY for charge balance ion selection.
  Does NOT modify any ion concentrations.
  HCl   → balance_anion = Cl
  H2SO4 → balance_anion = SO4
  NaOH  → balance_cation = Na

Public methods:
  run_analysis(request_dict)   → full pipeline
  switch_salt(run_id, salt_id) → re-graph from saved DB data (no re-run)
  get_available_salts()        → PHREEQC mineral list (cached)

CHANGELOG v4:
  - FIXED: _apply_ph_adjustment no longer modifies HCO3 or any ion.
    Previously subtracting 1.37 from HCO3 for HCl caused pH to drop to ~0.2.
  - ADDED: ph_mode="fixed" support with user-supplied fixed_ph value.
  - ADDED: adjustment_chemical auto-resolves balance_anion/cation.
  - REMOVED: _PH_RULES dict (was causing the pH=0.2 bug).
"""

import io
import logging
import math
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import boto3
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from botocore.exceptions import BotoCoreError, ClientError

from app.db.mongo import db
from app.services.phreeqc_service import PHREEQCService
from app.services.calculation_service import CalculationService
from app.services.cooling_tower_service import CoolingTowerService

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# DYNAMIC WATER PARAMETER KEY MAPPER
# Maps any OCR-extracted key → PHREEQC internal ion key
# ─────────────────────────────────────────────────────────────────────────────
_PARAM_ALIAS: Dict[str, str] = {
    # Calcium
    "calcium": "Ca", "ca": "Ca",
    # Magnesium
    "magnesium": "Mg", "mg": "Mg",
    # Sodium
    "sodium": "Na", "na": "Na",
    # Potassium
    "potassium": "K", "k": "K",
    # Chloride
    "chloride": "Cl", "cl": "Cl",
    # Sulfate / Sulphate
    "sulfate": "SO4", "sulphate": "SO4", "so4": "SO4",
    # Alkalinity / Bicarbonate — NOT Total Hardness
    "alkalinity": "HCO3", "bicarbonate": "HCO3", "hco3": "HCO3",
    "total_alkalinity": "HCO3", "m_alkalinity": "HCO3",
    # Silica
    "silica": "SiO2", "sio2": "SiO2", "silicon": "SiO2",
    # Barium
    "barium": "Ba", "ba": "Ba",
    # Strontium
    "strontium": "Sr", "sr": "Sr",
    # Iron
    "iron": "Fe", "fe": "Fe",
    # pH
    "ph": "pH",
    # Temperature
    "temperature": "Temperature", "temp": "Temperature",
    # Nitrate
    "nitrate": "NO3", "no3": "NO3",
    # Fluoride
    "fluoride": "F", "f": "F",
    # Phosphate
    "phosphate": "PO4", "po4": "PO4",
    # Manganese
    "manganese": "Mn", "mn": "Mn",
    # Potassium (alternate)
    "k_": "K",
}

# Keys to explicitly SKIP — these are not PHREEQC ions
_SKIP_KEYS = {
    "total_hardness", "total_dissolved_solids", "tds",
    "electrical_conductivity", "conductivity", "turbidity",
    "total_coliform", "e_coli", "fecal_coliform",
    "bod", "cod", "toc",
    "arsenic", "lead", "cadmium", "chromium", "mercury",
    "cyanide", "phenolic_compounds", "nitrite",
}

# ─────────────────────────────────────────────────────────────────────────────
# ADJUSTMENT CHEMICAL → BALANCE ION MAPPING
# Used ONLY for charge balance ion selection in PHREEQC.
# Does NOT affect ion concentrations or pH.
# ─────────────────────────────────────────────────────────────────────────────
_CHEMICAL_BALANCE_MAP: Dict[str, Dict[str, str]] = {
    "HCL":   {"balance_anion": "Cl"},
    "H2SO4": {"balance_anion": "SO4"},
    "NAOH":  {"balance_cation": "Na"},
}

# Colour hex values
_COLOUR_HEX = {"green": "#2ECC71", "yellow": "#F1C40F", "red": "#E74C3C", "error": "#BDC3C7"}


def _map_water_params(raw: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convert dynamic OCR keys → internal PHREEQC ion keys.
    Preserves unit information for unit-aware PHREEQC input building.
    Returns dict: { ion_key: {"value": float, "unit": str} }
    """
    out: Dict[str, Any] = {}
    for key, val in raw.items():
        norm = key.lower().replace(" ", "_").replace("-", "_")

        # Explicitly skip non-ion parameters
        if norm in _SKIP_KEYS:
            continue

        ion = _PARAM_ALIAS.get(norm)
        if ion is None:
            skip_match = any(s in norm for s in ["hardness", "dissolved_solid", "conductivity",
                                                   "coliform", "turbidity", "phenol"])
            if skip_match:
                continue
            for alias, mapped in _PARAM_ALIAS.items():
                if alias in norm or norm in alias:
                    ion = mapped
                    break
        if ion is None:
            continue

        # Extract numeric value and unit
        if isinstance(val, dict):
            numeric = val.get("value")
            unit    = val.get("unit", "mg/L") or "mg/L"
        elif isinstance(val, (int, float)):
            numeric = val
            unit    = "mg/L"
        else:
            continue

        if numeric is None:
            continue
        try:
            numeric = float(numeric)
        except (TypeError, ValueError):
            continue

        if ion != "pH" and numeric <= 0:
            continue

        # Store with unit for unit-aware PHREEQC input
        out[ion] = {"value": numeric, "unit": unit.strip()}

    return out


def _get_ion_value(mapped: Dict[str, Any], ion: str) -> Optional[float]:
    """Get numeric value from mapped params."""
    v = mapped.get(ion)
    if v is None:
        return None
    if isinstance(v, dict):
        return float(v.get("value", 0))
    return float(v)


def _get_ion_unit(mapped: Dict[str, Any], ion: str) -> str:
    """Get unit from mapped params."""
    v = mapped.get(ion)
    if isinstance(v, dict):
        return v.get("unit", "mg/L") or "mg/L"
    return "mg/L"


def _resolve_balance_ions(
    adjustment_chemical: Optional[str],
    balance_cation_override: Optional[str],
    balance_anion_override: Optional[str],
) -> Tuple[str, str]:
    """
    Resolve which ions to use for PHREEQC charge balance.

    Priority:
      1. Explicit overrides from request (balance_cation / balance_anion)
      2. Auto-resolved from adjustment_chemical
      3. Defaults: cation=Na, anion=Cl

    NOTE: adjustment_chemical does NOT modify ion concentrations.
          It only determines which ion absorbs the charge balance error.
    """
    balance_cation = balance_cation_override or "Na"
    balance_anion  = balance_anion_override  or "Cl"

    if adjustment_chemical:
        chem_key = (
            adjustment_chemical.upper()
            .replace("-", "")
            .replace("_", "")
            .replace(" ", "")
        )
        mapping = _CHEMICAL_BALANCE_MAP.get(chem_key)
        if mapping:
            if "balance_anion" in mapping and not balance_anion_override:
                balance_anion = mapping["balance_anion"]
                logger.info(
                    f"Auto-resolved balance_anion='{balance_anion}' "
                    f"from adjustment_chemical='{adjustment_chemical}'"
                )
            if "balance_cation" in mapping and not balance_cation_override:
                balance_cation = mapping["balance_cation"]
                logger.info(
                    f"Auto-resolved balance_cation='{balance_cation}' "
                    f"from adjustment_chemical='{adjustment_chemical}'"
                )
        else:
            logger.warning(
                f"Unknown adjustment_chemical '{adjustment_chemical}' — "
                f"using defaults: cation={balance_cation}, anion={balance_anion}"
            )

    return balance_cation, balance_anion


def _get_inhibited_salts(raw_material_chemistry: Optional[Dict]) -> List[str]:
    """
    Extract list of salt names that this raw material inhibits.
    From inhibitionFormulas[].salToInhibit
    """
    if not raw_material_chemistry:
        return []
    formulas = raw_material_chemistry.get("inhibitionFormulas") or []
    return [f.get("salToInhibit", "") for f in formulas if f.get("salToInhibit")]


def _color_code_for_salt(
    si: float,
    salt_name: str,
    inhibited_salts: List[str],
    thresholds: Dict[str, Any],
) -> str:
    """
    Client color logic:

    IF raw material inhibits this salt:
        green  → SI < yellow_lower  (treatment working)
        yellow → yellow_lower ≤ SI ≤ yellow_upper  (caution)
        red    → SI > yellow_upper  (treatment not working)

    ELSE (no inhibition for this salt):
        green → SI < 0   (undersaturated, no scaling risk)
        red   → SI >= 0  (supersaturated, scaling risk)
    """
    salt_lower = salt_name.lower()
    is_inhibited = any(s.lower() in salt_lower or salt_lower in s.lower()
                       for s in inhibited_salts if s)

    if is_inhibited:
        yellow_lower = thresholds.get("yellow_lower", -0.5)
        yellow_upper = thresholds.get("yellow_upper",  0.5)
        if si < yellow_lower:
            return "green"
        if si <= yellow_upper:
            return "yellow"
        return "red"
    else:
        return "green" if si < 0 else "red"


def _parse_thresholds(raw_material_chemistry: Optional[Dict], dosage_ppm: float = 2.0) -> Dict[str, Any]:
    """
    Extract color band thresholds from raw_material_chemistry.
    """
    if not raw_material_chemistry:
        return {
            "max_si_at_dose": 0.0,
            "yellow_lower":  -0.5,
            "yellow_upper":   0.5,
            "band_lower_pct": 5.0,
            "band_upper_pct": 5.0,
            "formula_used":   None,
        }

    def _to_float(v, default=0.0):
        try:
            if isinstance(v, str):
                v = v.replace("%", "").strip()
            return float(v)
        except (TypeError, ValueError):
            return default

    band_lower_pct = _to_float(raw_material_chemistry.get("bandLowerCushion"), 5.0)
    band_upper_pct = _to_float(raw_material_chemistry.get("bandUpperCushion"), 5.0)

    si_max = None
    formula_used = None
    inhibition_formulas = raw_material_chemistry.get("inhibitionFormulas", [])

    for formula_obj in (inhibition_formulas or []):
        formula_str = formula_obj.get("formulaForInhibitionPerformance", "")
        if not formula_str:
            continue
        try:
            import re as _re
            f = formula_str.replace("x", "*").replace("X", "*").replace("×", "*")
            m = _re.search(r"=\s*([\d.]+)\s*\*?\s*SI[^+\-]*\+\s*([\d.]+)", f)
            if not m:
                m = _re.search(r"=\s*([\d.]+)\s*\*?\s*SI[^+\-]*-\s*([\d.]+)", f)
                if m:
                    a, b = float(m.group(1)), -float(m.group(2))
                else:
                    continue
            else:
                a, b = float(m.group(1)), float(m.group(2))

            if a != 0:
                si_max = (dosage_ppm - b) / a
                formula_used = formula_str
                logger.info(f"SI_max from formula at dose={dosage_ppm}: SI_max={si_max:.4f}")
                break
        except Exception as e:
            logger.warning(f"Could not parse inhibition formula '{formula_str}': {e}")

    if si_max is None:
        si_max = 0.0

    yellow_lower = si_max * (1 - band_lower_pct / 100)
    yellow_upper = si_max * (1 + band_upper_pct / 100)

    return {
        "max_si_at_dose":  round(si_max, 4),
        "yellow_lower":    round(yellow_lower, 4),
        "yellow_upper":    round(yellow_upper, 4),
        "band_lower_pct":  band_lower_pct,
        "band_upper_pct":  band_upper_pct,
        "formula_used":    formula_used,
    }


# ─────────────────────────────────────────────────────────────────────────────
# CO2 PARTIAL PRESSURE CALCULATOR
# ─────────────────────────────────────────────────────────────────────────────

_CO2_AIRFLOW_ADJ: Dict[str, float] = {
    "counterflow": 0.0,
    "crossflow":   0.15,
}

_CO2_FILL_ADJ: Dict[str, float] = {
    "film fill - high-efficiency": -0.1,
    "film fill high efficiency":   -0.1,
    "film fill - standard":         0.0,
    "film fill standard":           0.0,
    "splash fill":                  0.2,
    "splash":                       0.2,
}

_CO2_DRAFT_ADJ: Dict[str, float] = {
    "forced draft":  0.0,
    "induced draft": -0.05,
    "natural draft":  0.15,
}


def _calculate_co2_factor(
    system_type: Optional[str],
    tower_type: Optional[str],
    fill_type: Optional[str],
    draft_type: Optional[str],
    approach_to_wb: Optional[float],
    co2_override: Optional[float],
) -> Optional[float]:
    """
    Calculate CO2(g) log partial pressure for EQUILIBRIUM_PHASES.

    Returns:
        float  → use this value in EQUILIBRIUM_PHASES CO2(g) <value> 100.0
        None   → Once Through Cooling, skip EQUILIBRIUM_PHASES entirely
    """
    if co2_override is not None:
        return co2_override

    sys = (system_type or "").lower().strip()

    if "once" in sys and "through" in sys:
        return None

    if "evaporative" in sys or "condenser" in sys:
        return -3.4

    base = -3.4

    airflow_key = (tower_type or "").lower().strip()
    base += _CO2_AIRFLOW_ADJ.get(airflow_key, 0.0)

    fill_key = (fill_type or "").lower().strip()
    base += _CO2_FILL_ADJ.get(fill_key, 0.0)

    draft_key = (draft_type or "").lower().strip()
    base += _CO2_DRAFT_ADJ.get(draft_key, 0.0)

    if approach_to_wb is not None:
        if approach_to_wb < 5:
            base += -0.1
        elif approach_to_wb <= 10:
            base += 0.0
        elif approach_to_wb <= 15:
            base += 0.1
        else:
            base += 0.2

    logger.info(
        f"CO2 factor: base=-3.4 → {base:.2f} "
        f"(airflow={tower_type}, fill={fill_type}, draft={draft_type}, approach={approach_to_wb}°F)"
    )
    return round(base, 2)


def _f_to_c(f: float) -> float:
    """Fahrenheit to Celsius."""
    return round((f - 32) * 5 / 9, 2)


def _to_celsius(value: float, unit: str) -> float:
    """Convert temperature to Celsius."""
    u = (unit or "").strip().upper()
    if u in ("F", "°F"):
        return _f_to_c(value)
    return round(value, 2)


# ─────────────────────────────────────────────────────────────────────────────
# MAIN SERVICE
# ─────────────────────────────────────────────────────────────────────────────

class SaturationService:
    """
    Orchestrates the full saturation analysis pipeline using client's
    exact 2-step PHREEQC workflow per CoC value.
    """

    COLOUR_MAP = _COLOUR_HEX

    def __init__(self):
        self.phreeqc   = PHREEQCService()
        self.s3_bucket = os.getenv("AWS_S3_BUCKET_NAME") or os.getenv("AWS_S3_BUCKET", "")
        self.s3_region = os.getenv("AWS_REGION", "us-east-1")
        self.s3_prefix = os.getenv("AWS_S3_SATURATION_PREFIX", "saturation-graphs/")
        self._s3       = None

    def _get_s3(self):
        if self._s3 is None:
            self._s3 = boto3.client(
                "s3",
                region_name=self.s3_region,
                aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
                aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
            )
        return self._s3

    # ── Build CoC list ────────────────────────────────────────────────────────
    @staticmethod
    def _build_coc_list(coc_min: float, coc_max: float, coc_interval: float) -> List[float]:
        """Return list of CoC values from min to max with given interval."""
        vals, c = [], coc_min
        interval = max(coc_interval, 0.01)
        while c <= coc_max + 1e-9:
            vals.append(round(c, 4))
            c += interval
        if not vals:
            vals = [coc_min]
        return vals

    # ── Step 1-3: CO2 equilibration at cold basin temp ────────────────────────
    async def _step1_natural_ph(
        self,
        mapped_params: Dict[str, Any],
        coc: float,
        cold_temp_c: float,
        co2_factor: Optional[float],
        database: str,
    ) -> float:
        """
        Run PHREEQC at cold basin temperature with CO2 equilibration.
        Returns the natural pH after CO2 degassing.
        Minerals multiplied by CoC (except pH, Temperature, pe).
        """
        if co2_factor is None:
            return float(_get_ion_value(mapped_params, "pH") or 7.0)

        concentrated = {}
        skip_keys = {"pH", "Temperature", "pe"}
        for k, v in mapped_params.items():
            if k in skip_keys:
                concentrated[k] = v
            elif isinstance(v, dict):
                concentrated[k] = {**v, "value": v["value"] * coc}
            else:
                concentrated[k] = float(v) * coc

        concentrated["Temperature"] = {"value": cold_temp_c, "unit": "°C"}

        try:
            result = await self.phreeqc.run_step1_co2_equilibration(
                concentrated, co2_factor, database
            )
            natural_ph = result.get("pH", _get_ion_value(mapped_params, "pH") or 7.0)
            logger.debug(f"  CoC={coc} cold={cold_temp_c}°C → natural pH={natural_ph:.3f}")
            return float(natural_ph)
        except Exception as e:
            logger.warning(f"Step 1-3 CO2 eq failed for CoC={coc}: {e}")
            return float(_get_ion_value(mapped_params, "pH") or 7.0)

    # ── Step 5-6: Final SI calculation at hot evaluation temp ─────────────────
    async def _step5_hot_temp_si(
        self,
        mapped_params: Dict[str, Any],
        coc: float,
        hot_temp_c: float,
        natural_ph: float,
        balance_anion: str,
        database: str,
    ) -> Dict[str, Any]:
        """
        Run PHREEQC at hot evaluation temperature with natural pH and charge balance.
        Minerals multiplied by CoC.
        """
        concentrated = {}
        skip_keys = {"pH", "Temperature", "pe"}
        for k, v in mapped_params.items():
            if k in skip_keys:
                concentrated[k] = v
            elif isinstance(v, dict):
                concentrated[k] = {**v, "value": v["value"] * coc}
            else:
                concentrated[k] = float(v) * coc

        concentrated["pH"]          = {"value": natural_ph, "unit": ""}
        concentrated["Temperature"] = {"value": hot_temp_c,  "unit": "°C"}

        try:
            result = await self.phreeqc.run_step5_hot_temp(
                concentrated, natural_ph, hot_temp_c, balance_anion, database
            )
            return result
        except Exception as e:
            logger.error(f"Step 5-6 failed for CoC={coc}, temp={hot_temp_c}°C: {e}")
            return {"saturation_indices": [], "ionic_strength": 0.0,
                    "charge_balance_error_pct": 0.0, "description_of_solution": {}}

    # ── STEP: run full 2-step pipeline per CoC × Temperature ─────────────────
    async def _run_two_step_pipeline(
        self,
        mapped_params: Dict[str, Any],
        coc_list: List[float],
        cold_temp_c: float,
        temp_list_c: List[float],
        co2_factor: Optional[float],
        salt_id: Optional[str],
        salts_of_interest: Optional[List[str]],
        thresholds: Dict[str, Any],
        inhibited_salts: List[str],
        balance_cation: str,
        balance_anion: str,
    ) -> Tuple[List[Dict[str, Any]], str]:
        """
        Client pseudo-code:
          Do CurrentTemp = temp_min to temp_max
            Do CoC = coc_min to coc_max
              Step 1: supply_temp + CO2 eq → natural pH  (skipped if ph_mode=fixed)
              Step 2: CurrentTemp + natural/fixed pH + charge balance → SI
            Loop
          Loop
        """
        max_coc  = max(coc_list)
        max_temp = max(temp_list_c)

        database = self.phreeqc.select_database(
            {k: v["value"] if isinstance(v, dict) else v for k, v in mapped_params.items()},
            ph_range=(6.0, 10.0),
            coc_range=(min(coc_list), max_coc),
            temp_range=(cold_temp_c, max_temp),
        )
        db_name = os.path.basename(database)
        logger.info(f"Database selected: {db_name}")

        color_salt = salt_id or (salts_of_interest[0] if salts_of_interest else None)
        results: List[Dict[str, Any]] = []

        # Cache natural pH per CoC (Step 1 only depends on CoC, not evaluation temp)
        natural_ph_cache: Dict[float, float] = {}

        total = len(temp_list_c) * len(coc_list)
        done  = 0

        for hot_temp_c in temp_list_c:
            for coc in coc_list:
                done += 1
                logger.info(f"[{done}/{total}] CoC={coc}, eval_temp={hot_temp_c}°C ...")

                # ── Step 1: natural pH at cold supply temp (cached per CoC) ──
                if coc not in natural_ph_cache:
                    natural_ph = await self._step1_natural_ph(
                        mapped_params, coc, cold_temp_c, co2_factor, database
                    )
                    natural_ph_cache[coc] = natural_ph
                else:
                    natural_ph = natural_ph_cache[coc]

                # ── Step 2: SI at evaluation temp ─────────────────────────────
                phreeqc_result = await self._step5_hot_temp_si(
                    mapped_params, coc, hot_temp_c, natural_ph, balance_anion, database
                )

                # Build SI detail dict + SR (Saturation Ratio = 10^SI)
                si_detail: Dict[str, Any] = {}
                for item in phreeqc_result.get("saturation_indices", []):
                    if isinstance(item, dict):
                        name    = item.get("mineral_name", "")
                        si_val  = round(item.get("si_value", 0.0), 4)
                        si_detail[name] = {
                            "SI":               si_val,
                            "SR":               round(10 ** si_val, 6),
                            "log_IAP":          item.get("log_IAP"),
                            "log_K":            item.get("log_K"),
                            "phase":            item.get("phase"),
                            "chemical_formula": item.get("chemical_formula"),
                        }

                def _find_si_val(si_dict: Dict, target: Optional[str]) -> Optional[float]:
                    if not target:
                        return None
                    if target in si_dict:
                        return si_dict[target].get("SI")
                    tl = target.lower()
                    for k, v in si_dict.items():
                        if k.lower() == tl:
                            return v.get("SI")
                    return None

                selected_si = _find_si_val(si_detail, color_salt)

                if selected_si is not None:
                    color = _color_code_for_salt(
                        selected_si, color_salt or "", inhibited_salts, thresholds
                    )
                else:
                    color = "green"

                per_salt_colors: Dict[str, str] = {}
                for mineral_name, mineral_data in si_detail.items():
                    per_salt_colors[mineral_name] = _color_code_for_salt(
                        mineral_data["SI"], mineral_name, inhibited_salts, thresholds
                    )

                desc = phreeqc_result.get("description_of_solution", {})

                results.append({
                    "_grid_CoC":               coc,
                    "_grid_temp":              hot_temp_c,
                    "_grid_pH":                natural_ph,
                    "_cold_temp_c":            cold_temp_c,
                    "_natural_ph_at_cold":     natural_ph,
                    "saturation_indices":      si_detail,
                    "description_of_solution": desc,
                    "distribution_of_species": phreeqc_result.get("distribution_of_species", {}),
                    "color_code":              color,
                    "per_salt_colors":         per_salt_colors,
                    "ionic_strength":          phreeqc_result.get("ionic_strength", 0.0),
                    "charge_balance_error_pct": phreeqc_result.get("charge_balance_error_pct", 0.0),
                    "electrical_balance":      phreeqc_result.get("electrical_balance", 0.0),
                    "specific_conductance":    desc.get("specific_conductance"),
                    "density":                 desc.get("density"),
                })

        logger.info(f"Pipeline complete: {len(results)} grid points ({len(temp_list_c)} temps × {len(coc_list)} CoC)")
        return results, db_name

    # ── STEP: generate 3D graph ───────────────────────────────────────────────
    def _generate_graph(
        self,
        results: List[Dict[str, Any]],
        salt_id: Optional[str],
        run_id: str,
        temp_unit: str,
    ) -> bytes:
        display_salt = salt_id or "All Salts"

        def _get_si_for_salt(si_dict: Dict, target: str) -> Optional[float]:
            if target in si_dict:
                val = si_dict[target]
                return val.get("SI") if isinstance(val, dict) else float(val)
            target_lower = target.lower()
            for k, v in si_dict.items():
                if k.lower() == target_lower:
                    return v.get("SI") if isinstance(v, dict) else float(v)
            return None

        if salt_id:
            valid = [r for r in results if _get_si_for_salt(r["saturation_indices"], salt_id) is not None]
        else:
            valid = results

        if not valid:
            raise ValueError("No valid PHREEQC results to plot")

        x_vals = np.array([r["_grid_CoC"]  for r in valid])
        y_vals = np.array([r["_grid_temp"] for r in valid])

        if salt_id:
            z_vals = np.array([_get_si_for_salt(r["saturation_indices"], salt_id) for r in valid])
        else:
            first_salt = next(iter(valid[0]["saturation_indices"]), None)
            z_vals = np.array([
                r["saturation_indices"].get(first_salt, {}).get("SI", 0.0) for r in valid
            ])

        colors = [
            self.COLOUR_MAP.get(
                r.get("per_salt_colors", {}).get(
                    next((k for k in r.get("per_salt_colors", {}) if k.lower() == (salt_id or "").lower()), None
                    ) or r.get("color_code", "green"),
                    r.get("color_code", "green")
                ),
                "#BDC3C7"
            )
            for r in valid
        ]

        y_label = "Temperature (°C)"
        if temp_unit.upper() == "F":
            y_display = np.array([(t * 9/5) + 32 for t in y_vals])
            y_label = "Temperature (°F)"
        else:
            y_display = y_vals

        fig = plt.figure(figsize=(13, 8), facecolor="#1A1A2E")
        ax  = fig.add_subplot(111, projection="3d", facecolor="#16213E")

        unique_x = sorted(set(x_vals))
        unique_y = sorted(set(y_display))
        dx = max(0.3, (max(unique_x) - min(unique_x)) / max(len(unique_x), 1) * 0.7) if len(unique_x) > 1 else 0.5
        dy = max(1.5, (max(unique_y) - min(unique_y)) / max(len(unique_y), 1) * 0.7) if len(unique_y) > 1 else 5.0

        for xi, yi, zi, color in zip(x_vals, y_display, z_vals, colors):
            dz = abs(zi) if zi != 0 else 0.01
            z_bottom = min(zi, 0.0)
            ax.bar3d(xi - dx/2, yi - dy/2, z_bottom, dx, dy, dz,
                     color=color, alpha=0.85, shade=True)

        if x_vals.size and y_display.size:
            xx = np.linspace(x_vals.min() - dx, x_vals.max() + dx, 2)
            yy = np.linspace(y_display.min() - dy, y_display.max() + dy, 2)
            XX, YY = np.meshgrid(xx, yy)
            ax.plot_surface(XX, YY, np.zeros_like(XX), alpha=0.12, color="white")

        ax.set_xlabel("Cycles of Concentration", color="white", labelpad=12, fontsize=10)
        ax.set_ylabel(y_label,                   color="white", labelpad=12, fontsize=10)
        ax.set_zlabel(f"SI — {display_salt}",    color="white", labelpad=12, fontsize=10)
        ax.tick_params(colors="white", labelsize=8)
        for pane in (ax.xaxis.pane, ax.yaxis.pane, ax.zaxis.pane):
            pane.fill = False
            pane.set_edgecolor("#444466")
        ax.grid(True, color="#333355", linewidth=0.4)
        ax.set_title(f"Saturation Analysis — {display_salt}\n(Run: {run_id})",
                     color="white", fontsize=13, fontweight="bold", pad=18)

        from matplotlib.patches import Patch
        ax.legend(
            handles=[
                Patch(facecolor=_COLOUR_HEX["green"],  label="Protected"),
                Patch(facecolor=_COLOUR_HEX["yellow"], label="Caution"),
                Patch(facecolor=_COLOUR_HEX["red"],    label="Scale Risk"),
            ],
            loc="upper left", facecolor="#1A1A2E", edgecolor="#444466",
            labelcolor="white", fontsize=9,
        )
        ax.view_init(elev=25, azim=225)
        fig.tight_layout()

        buf = io.BytesIO()
        plt.savefig(buf, format="png", dpi=150, bbox_inches="tight",
                    facecolor=fig.get_facecolor())
        plt.close(fig)
        buf.seek(0)
        return buf.read()

    # ── STEP: upload to S3 ───────────────────────────────────────────────────
    def _upload_s3(self, png: bytes, run_id: str, suffix: str = "") -> str:
        if not self.s3_bucket:
            logger.warning("AWS_S3_BUCKET not set — skipping S3 upload")
            return f"local://{run_id}{suffix}.png"
        key = f"{self.s3_prefix}{run_id}{suffix}.png"
        try:
            s3 = self._get_s3()
            s3.put_object(
                Bucket=self.s3_bucket, Key=key,
                Body=png, ContentType="image/png",
            )
            url = s3.generate_presigned_url(
                "get_object",
                Params={"Bucket": self.s3_bucket, "Key": key},
                ExpiresIn=604800,
            )
            logger.info(f"Graph uploaded → presigned URL generated for {key}")
            return url
        except (BotoCoreError, ClientError) as e:
            logger.error(f"S3 upload failed: {e} — returning placeholder URL")
            return f"s3-upload-failed://{run_id}{suffix}.png"

    # ── STEP: build graph_data JSON (for frontend 3D renderer) ───────────────
    @staticmethod
    def _build_graph_data(
        results: List[Dict[str, Any]],
        salt_id: Optional[str],
        temp_unit: str,
    ) -> Dict[str, Any]:
        """
        Build Plotly-ready 3D bar chart data.
        """
        temp_label = f"Temperature ({'°F' if temp_unit.upper() == 'F' else '°C'})"

        color_labels = {
            "green":  "Protected (Green)",
            "yellow": "Caution (Yellow)",
            "red":    "Scale Risk (Red)",
            "error":  "No Data",
        }

        def _get_si(si_dict: Dict, target: Optional[str]) -> Optional[float]:
            if not target:
                return None
            if target in si_dict:
                v = si_dict[target]
                return v.get("SI") if isinstance(v, dict) else float(v)
            tl = target.lower()
            for k, v in si_dict.items():
                if k.lower() == tl:
                    return v.get("SI") if isinstance(v, dict) else float(v)
            return None

        bars = []
        for r in results:
            temp_display = round(
                (r["_grid_temp"] * 9/5 + 32) if temp_unit.upper() == "F" else r["_grid_temp"], 1
            )
            si_val = _get_si(r["saturation_indices"], salt_id)

            all_si = {
                mineral: (
                    {
                        "SI":               info.get("SI"),
                        "log_IAP":          info.get("log_IAP"),
                        "log_K":            info.get("log_K"),
                        "chemical_formula": info.get("chemical_formula"),
                        "phase":            info.get("phase"),
                    }
                    if isinstance(info, dict) else {"SI": float(info)}
                )
                for mineral, info in r["saturation_indices"].items()
            }

            desc = r.get("description_of_solution") or {}

            bars.append({
                "x":         r["_grid_CoC"],
                "y":         si_val,
                "z":         temp_display,
                "color":     r["color_code"],
                "color_hex": _COLOUR_HEX.get(r["color_code"], "#BDC3C7"),
                "click_data": {
                    "CoC":              r["_grid_CoC"],
                    "temperature":      temp_display,
                    "temperature_unit": "°F" if temp_unit.upper() == "F" else "°C",
                    "pH":               r["_grid_pH"],
                    "selected_salt":    salt_id,
                    "SI":               si_val,
                    "status":           color_labels.get(r["color_code"], r["color_code"]),
                    "ionic_strength":   r.get("ionic_strength"),
                    "charge_balance_error_pct": r.get("charge_balance_error_pct"),
                    "density":          desc.get("density"),
                    "activity_of_water": desc.get("activity_of_water"),
                    "all_saturation_indices": all_si,
                },
                "tooltip": {
                    "CoC":              r["_grid_CoC"],
                    "temperature":      f"{temp_display} {'°F' if temp_unit.upper() == 'F' else '°C'}",
                    "pH":               r["_grid_pH"],
                    "SI":               si_val,
                    "salt":             salt_id,
                    "ionic_strength":   r.get("ionic_strength"),
                    "charge_balance_error_pct": r.get("charge_balance_error_pct"),
                    "density":          desc.get("density"),
                    "activity_of_water": desc.get("activity_of_water"),
                    "all_saturation_indices": all_si,
                },
            })

        unique_coc  = sorted(set(b["x"] for b in bars))
        unique_temp = sorted(set(b["z"] for b in bars))

        def _make_bar_mesh(x_center, z_center, y_top, color_hex, dx=0.4, dz=4.0):
            x0, x1 = x_center - dx/2, x_center + dx/2
            z0, z1 = z_center - dz/2, z_center + dz/2
            y0, y1 = min(y_top, 0.0), max(y_top, 0.0)
            vx = [x0,x1,x1,x0, x0,x1,x1,x0]
            vy = [y0,y0,y0,y0, y1,y1,y1,y1]
            vz = [z0,z0,z1,z1, z0,z0,z1,z1]
            i = [0,0,1,1,2,2,3,3,4,4,0,0]
            j = [1,2,2,5,3,6,0,7,5,6,4,5]
            k = [2,3,5,6,6,7,7,4,6,7,5,1]
            return {
                "type":       "mesh3d",
                "x": vx, "y": vy, "z": vz,
                "i": i, "j": j, "k": k,
                "color":      color_hex,
                "opacity":    0.85,
                "flatshading": True,
                "showscale":  False,
                "lighting":   {"ambient": 0.6, "diffuse": 0.8, "specular": 0.3},
            }

        if len(unique_coc) > 1:
            dx = (max(unique_coc) - min(unique_coc)) / len(unique_coc) * 0.7
        else:
            dx = 0.4

        if len(unique_temp) > 1:
            dz = (max(unique_temp) - min(unique_temp)) / len(unique_temp) * 0.7
        else:
            dz = 4.0

        plotly_traces = []

        legend_added = set()
        for bar in bars:
            color = bar["color"]
            if color not in legend_added:
                plotly_traces.append({
                    "type":   "scatter3d",
                    "mode":   "markers",
                    "name":   color_labels.get(color, color),
                    "x":      [bar["x"]],
                    "y":      [bar["z"]],
                    "z":      [bar["y"] if bar["y"] is not None else 0],
                    "marker": {"size": 0.1, "color": _COLOUR_HEX.get(color, "#BDC3C7")},
                    "showlegend": True,
                    "hoverinfo": "skip",
                })
                legend_added.add(color)

        for bar in bars:
            si = bar["y"] if bar["y"] is not None else 0.0
            mesh = _make_bar_mesh(
                x_center=bar["x"],
                z_center=bar["z"],
                y_top=si,
                color_hex=_COLOUR_HEX.get(bar["color"], "#BDC3C7"),
                dx=dx,
                dz=dz,
            )
            mesh["showlegend"] = False
            plotly_traces.append(mesh)

            cd = bar["click_data"]
            plotly_traces.append({
                "type":       "scatter3d",
                "mode":       "markers",
                "x":          [bar["x"]],
                "y":          [bar["z"]],
                "z":          [si],
                "marker":     {"size": 8, "color": _COLOUR_HEX.get(bar["color"], "#BDC3C7"), "opacity": 0.01},
                "text":       [si],
                "customdata": [cd],
                "hovertemplate": (
                    f"<b>CoC:</b> {cd['CoC']}<br>"
                    f"<b>Temp:</b> {cd['temperature']} {cd['temperature_unit']}<br>"
                    f"<b>pH:</b> {cd['pH']}<br>"
                    f"<b>SI ({salt_id}):</b> {si:.4f}<br>"
                    f"<b>Status:</b> {cd['status']}"
                    "<extra></extra>"
                ),
                "showlegend": False,
            })

        x_vals = [b["x"] for b in bars]
        z_vals = [b["z"] for b in bars]
        y_vals = [b["y"] for b in bars if b["y"] is not None]

        plotly_layout = {
            "title": f"Saturation Analysis — {salt_id or 'All Salts'}",
            "scene": {
                "xaxis": {
                    "title": "Cycles of Concentration",
                    "range": [min(x_vals) - 0.5, max(x_vals) + 0.5] if x_vals else [0, 10],
                },
                "yaxis": {
                    "title": temp_label,
                    "range": [min(z_vals) - 5, max(z_vals) + 5] if z_vals else [0, 200],
                },
                "zaxis": {
                    "title": f"Saturation Index ({salt_id or 'SI'})",
                    "range": [
                        min(y_vals) - 0.5 if y_vals else -2,
                        max(y_vals) + 0.5 if y_vals else 2,
                    ],
                },
                "bgcolor": "#16213E",
                "xaxis_gridcolor": "#333355",
                "yaxis_gridcolor": "#333355",
                "zaxis_gridcolor": "#333355",
            },
            "paper_bgcolor": "#1A1A2E",
            "font":   {"color": "white"},
            "legend": {"bgcolor": "#1A1A2E", "bordercolor": "#444466"},
            "margin": {"l": 0, "r": 0, "t": 40, "b": 0},
        }

        return {
            "type":          "3d_bar",
            "salt_id":       salt_id,
            "temp_unit":     temp_unit,
            "total_points":  len(bars),
            "axes": {
                "x": {"label": "Cycles of Concentration", "values": unique_coc},
                "y": {"label": f"Saturation Index ({salt_id or 'SI'})", "unit": "SI"},
                "z": {"label": temp_label, "values": unique_temp},
            },
            "bars":           bars,
            "plotly_traces":  plotly_traces,
            "plotly_layout":  plotly_layout,
            "color_map":      _COLOUR_HEX,
            "color_labels":   color_labels,
        }

    # ── STEP: enrich each grid point with all calculated values ─────────────
    @staticmethod
    async def _enrich_grid_points(
        results: List[Dict[str, Any]],
        base_water_parameters: Dict[str, Any],
        req: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """
        For each grid point, calculate deposition indices, water balance,
        chemical feedrate, and corrosion rates.
        """
        calc_svc = CalculationService()
        ct_svc   = CoolingTowerService()

        asset_info       = req.get("asset_info") or {}
        raw_mat          = req.get("raw_material_chemistry") or {}
        product_blend    = req.get("product_blend") or {}
        dosage_ppm       = float(req.get("dosage_ppm") or 2.0)
        temp_unit        = req.get("temp_unit", "C")

        recirc_rate_gpm  = float(asset_info.get("recirculationRate") or 0)
        hot_temp_f       = float(asset_info.get("hotWaterTempF") or 0)
        cold_temp_f      = float(asset_info.get("coldWaterTempF") or 0)
        wet_bulb_f       = float(asset_info.get("wetBulbTempF") or 0)
        drift_pct        = float(asset_info.get("driftPercent") or 0.1)
        evap_factor      = float(asset_info.get("evaporationFactorPercent") or 85.0)
        metallurgy       = asset_info.get("systemMetallurgy") or []

        product_cost_per_lb = float(product_blend.get("costPerLb") or 0)
        product_name        = product_blend.get("productName") or "Product"

        enriched = []
        for r in results:
            coc      = r["_grid_CoC"]
            temp_c   = r["_grid_temp"]
            ph       = r["_grid_pH"]
            ionic_s  = r.get("ionic_strength", 0.0)

            conc_params: Dict[str, Any] = {}
            for key, val in base_water_parameters.items():
                if isinstance(val, dict):
                    raw_val = val.get("value", 0)
                    unit    = val.get("unit", "mg/L")
                else:
                    raw_val = val
                    unit    = "mg/L"
                try:
                    numeric = float(raw_val)
                except (TypeError, ValueError):
                    numeric = 0.0
                if key.lower() in ("ph", "temperature", "temp"):
                    conc_params[key] = {"value": numeric, "unit": unit}
                else:
                    conc_params[key] = {"value": round(numeric * coc, 4), "unit": unit}

            conc_params["pH"]          = {"value": ph,     "unit": ""}
            conc_params["Temperature"] = {"value": temp_c, "unit": "C"}

            def _get_si_val(name: str) -> Optional[float]:
                for k, v in r["saturation_indices"].items():
                    if k.lower() == name.lower():
                        return v.get("SI") if isinstance(v, dict) else float(v)
                return None

            calcite_si  = _get_si_val("Calcite")
            gypsum_si   = _get_si_val("Gypsum")
            dolomite_si = _get_si_val("Dolomite")
            anhydrite_si= _get_si_val("Anhydrite")

            indices: Dict[str, Any] = {}

            if calcite_si is not None:
                lsi_val = round(calcite_si, 3)
                if lsi_val > 0.5:
                    lsi_interp, lsi_risk = "Scaling Tendency", "Scale Forming"
                elif lsi_val > 0:
                    lsi_interp, lsi_risk = "Slight Scaling Tendency", "Low Scale Risk"
                elif lsi_val >= -0.5:
                    lsi_interp, lsi_risk = "Slightly Corrosive", "Low Corrosion"
                else:
                    lsi_interp, lsi_risk = "Corrosive", "Corrosive"
                indices["lsi"] = {
                    "lsi": lsi_val, "pH_actual": ph,
                    "interpretation": lsi_interp, "risk": lsi_risk,
                    "source": "PHREEQC Calcite SI",
                }
            else:
                try:
                    indices["lsi"] = await calc_svc.calculate_lsi(conc_params)
                except Exception as e:
                    indices["lsi"] = {"error": str(e)}

            if calcite_si is not None:
                lsi_val = calcite_si
                rsi_val = round(ph - 2 * lsi_val, 3)
                if rsi_val < 5.5:
                    rsi_interp, rsi_risk = "Heavy Scaling", "High Scale Risk"
                elif rsi_val < 6.2:
                    rsi_interp, rsi_risk = "Moderate Scaling", "Moderate Scale Risk"
                elif rsi_val < 7.0:
                    rsi_interp, rsi_risk = "Slight Scaling", "Low Scale Risk"
                elif rsi_val < 7.5:
                    rsi_interp, rsi_risk = "Balanced", "Balanced"
                elif rsi_val < 9.0:
                    rsi_interp, rsi_risk = "Slight Corrosion", "Low Corrosion"
                else:
                    rsi_interp, rsi_risk = "Heavy Corrosion", "High Corrosion"
                indices["ryznar"] = {
                    "ri": rsi_val, "pH_actual": ph,
                    "interpretation": rsi_interp, "risk": rsi_risk,
                    "source": "Derived from PHREEQC Calcite SI",
                }
            else:
                try:
                    indices["ryznar"] = await calc_svc.calculate_ryznar(conc_params)
                except Exception as e:
                    indices["ryznar"] = {"error": str(e)}

            try:
                indices["puckorius"] = await calc_svc.calculate_puckorius(conc_params)
            except Exception as e:
                indices["puckorius"] = {"error": str(e)}

            try:
                indices["larson_skold"] = await calc_svc.calculate_larson_skold(conc_params)
            except Exception as e:
                indices["larson_skold"] = {"error": str(e)}

            try:
                indices["stiff_davis"] = await calc_svc.calculate_stiff_davis(conc_params, ionic_s)
            except Exception as e:
                indices["stiff_davis"] = {"error": str(e)}

            eq_phases = r.get("equilibrium_phases", {})
            calcite_moles = eq_phases.get("Calcite")
            if calcite_moles is not None:
                ccpp_ppm = round(calcite_moles * 100.09 * 1000, 2)
            elif calcite_si is not None:
                ca_val = 0.0
                for k, v in base_water_parameters.items():
                    if k.lower() in ("calcium", "ca"):
                        ca_val = float(v.get("value", 0) if isinstance(v, dict) else v) * coc
                        break
                ca_as_caco3 = ca_val * (100.09 / 40.08)
                ccpp_ppm = round(calcite_si * ca_as_caco3 / 10, 2)
            else:
                ccpp_ppm = None

            if ccpp_ppm is not None:
                if ccpp_ppm > 15:
                    ccpp_interp, ccpp_risk = "Heavy Scale Forming", "High Scale Risk"
                elif ccpp_ppm > 0:
                    ccpp_interp, ccpp_risk = "Slight Scale Forming", "Moderate Scale Risk"
                elif ccpp_ppm >= -15:
                    ccpp_interp, ccpp_risk = "Slight Dissolution", "Low Corrosion"
                else:
                    ccpp_interp, ccpp_risk = "Corrosive", "Corrosive"
                indices["ccpp"] = {
                    "ccpp_ppm": ccpp_ppm,
                    "interpretation": ccpp_interp,
                    "risk": ccpp_risk,
                    "source": "PHREEQC equilibrium phases" if calcite_moles is not None else "Estimated from Calcite SI",
                }
            else:
                indices["ccpp"] = {"ccpp_ppm": None, "interpretation": "N/A", "risk": "N/A"}

            water_balance: Dict[str, Any] = {}
            if recirc_rate_gpm > 0 and hot_temp_f > 0 and cold_temp_f > 0:
                try:
                    wb = await ct_svc.calculate_tower_water_balance(
                        recirculation_rate_gpm=recirc_rate_gpm,
                        hot_water_temp_f=hot_temp_f,
                        cold_water_temp_f=cold_temp_f,
                        wet_bulb_temp_f=wet_bulb_f or (cold_temp_f - 10),
                        coc=coc,
                        drift_percent=drift_pct,
                        evaporation_factor_percent=evap_factor,
                    )
                    water_balance = {
                        "blowdown_rate_gpm":  wb["blowdown"]["blowdown_rate_gpm"],
                        "makeup_rate_gpm":    wb["makeup"]["makeup_rate_gpm"],
                        "evaporation_gpm":    wb["evaporation"]["evaporation_rate_gpm"],
                        "range_f":            wb["range"]["range_f"],
                        "approach_f":         wb["approach"]["approach_f"],
                        "efficiency_pct":     wb["efficiency"]["efficiency_percent"],
                        "heat_load_btu_hr":   wb["heat_load"]["heat_load_btu_hr"],
                        "cooling_tons":       wb["cooling_tons"]["cooling_tons"],
                    }
                except Exception as e:
                    logger.warning(f"Water balance failed for CoC={coc}: {e}")
                    water_balance = {"error": str(e)}
            else:
                water_balance = {"note": "Provide asset_info with recirculationRate, hotWaterTempF, coldWaterTempF"}

            chemical_data: Dict[str, Any] = {}
            bd_gpm = water_balance.get("blowdown_rate_gpm") if isinstance(water_balance.get("blowdown_rate_gpm"), (int, float)) else None
            if bd_gpm and bd_gpm > 0 and dosage_ppm > 0:
                try:
                    day_result  = await ct_svc.calculate_chemical_required_per_day(dosage_ppm, bd_gpm)
                    lbs_per_day = day_result["chemical_lbs_per_day"]
                    kg_per_day  = round(lbs_per_day * 0.453592, 3)
                    kg_per_year = round(kg_per_day * 350, 1)
                    lbs_per_year = round(lbs_per_day * 350, 1)
                    chemical_data = {
                        "product_name":   product_name,
                        "dosage_ppm":     dosage_ppm,
                        "lbs_per_day":    lbs_per_day,
                        "kg_per_day":     kg_per_day,
                        "lbs_per_year":   lbs_per_year,
                        "kg_per_year":    kg_per_year,
                    }
                    if product_cost_per_lb > 0:
                        cost_result = await ct_svc.calculate_chemical_cost(dosage_ppm, product_cost_per_lb)
                        chemical_data["cost_per_million_lbs_bd"] = cost_result["cost_per_million_lbs_bd"]
                        chemical_data["annual_cost_usd"] = round(lbs_per_year * product_cost_per_lb, 2)
                except Exception as e:
                    logger.warning(f"Chemical feedrate failed: {e}")
                    chemical_data = {"error": str(e)}
            else:
                chemical_data = {"note": "Provide asset_info.recirculationRate and dosage_ppm for feedrate"}

            corrosion: Dict[str, Any] = {}
            si_dict_flat = {
                k: (v.get("SI") if isinstance(v, dict) else float(v))
                for k, v in r["saturation_indices"].items()
            }
            do_ppm = max(0.0, round(14.62 - 0.3898 * temp_c + 0.006969 * temp_c**2 - 0.00005896 * temp_c**3, 2))

            metals_to_calc = list(set(["mild_steel", "copper", "admiralty_brass"] + [
                m.lower().replace(" ", "_").replace("-", "_") for m in metallurgy
            ]))

            for metal_key in metals_to_calc:
                try:
                    if "mild_steel" in metal_key or "steel" in metal_key:
                        result_cr = await calc_svc.calculate_mild_steel_corrosion(
                            conc_params, si_dict_flat, do_ppm, temp_c
                        )
                        corrosion["mild_steel"] = {**result_cr, "do_ppm_used": do_ppm}
                    elif "copper" in metal_key:
                        result_cr = await calc_svc.calculate_copper_corrosion(
                            conc_params, si_dict_flat, do_ppm, temp_c, ph
                        )
                        corrosion["copper"] = {**result_cr, "do_ppm_used": do_ppm}
                    elif "admiralty" in metal_key or "brass" in metal_key:
                        result_cr = await calc_svc.calculate_copper_corrosion(
                            conc_params, si_dict_flat, do_ppm, temp_c, ph
                        )
                        cr_adj = round(result_cr["cr_mpy"] * 0.85, 2)
                        corrosion["admiralty_brass"] = {**result_cr, "cr_mpy": cr_adj, "do_ppm_used": do_ppm}
                except Exception as e:
                    logger.warning(f"Corrosion calc failed for {metal_key}: {e}")
                    corrosion[metal_key] = {"error": str(e)}

            enriched.append({
                **r,
                "indices":       indices,
                "water_balance": water_balance,
                "chemical":      chemical_data,
                "corrosion":     corrosion,
            })

        return enriched

    # ── STEP: build interactive chart data ──────────────────────────────────
    @staticmethod
    def _build_chart_data(
        results: List[Dict[str, Any]],
        salt_id: Optional[str],
        temp_unit: str,
    ) -> Dict[str, Any]:
        """
        Build frontend-ready structured data for interactive 3D bar chart.
        """
        temp_suffix = "°F" if temp_unit.upper() == "F" else "°C"

        def _get_si(si_dict: Dict, target: Optional[str]) -> Optional[float]:
            if not target:
                return None
            if target in si_dict:
                v = si_dict[target]
                return v.get("SI") if isinstance(v, dict) else float(v)
            tl = target.lower()
            for k, v in si_dict.items():
                if k.lower() == tl:
                    return v.get("SI") if isinstance(v, dict) else float(v)
            return None

        points = []
        for r in results:
            temp_display = round(
                (r["_grid_temp"] * 9/5 + 32) if temp_unit.upper() == "F" else r["_grid_temp"], 2
            )
            si_val = _get_si(r["saturation_indices"], salt_id)
            desc   = r.get("description_of_solution") or {}

            all_si = {
                mineral: {
                    "SI":               info.get("SI") if isinstance(info, dict) else float(info),
                    "log_IAP":          info.get("log_IAP") if isinstance(info, dict) else None,
                    "log_K":            info.get("log_K") if isinstance(info, dict) else None,
                    "chemical_formula": info.get("chemical_formula") if isinstance(info, dict) else None,
                }
                for mineral, info in r["saturation_indices"].items()
            }

            points.append({
                "coc":         r["_grid_CoC"],
                "temperature": temp_display,
                "ph":          r["_grid_pH"],
                "si":          si_val,
                "color":       r["color_code"],
                "color_hex":   _COLOUR_HEX.get(r["color_code"], "#BDC3C7"),
                "ionic_strength":            r.get("ionic_strength"),
                "charge_balance_error_pct":  r.get("charge_balance_error_pct"),
                "activity_of_water":         desc.get("activity_of_water"),
                "all_si": all_si,
                "indices":       r.get("indices", {}),
                "water_balance": r.get("water_balance", {}),
                "chemical":      r.get("chemical", {}),
                "corrosion":     r.get("corrosion", {}),
                "description_of_solution": desc,
                "distribution_of_species": r.get("distribution_of_species", {}),
                "electrical_balance":      r.get("electrical_balance", 0.0),
            })

        unique_coc  = sorted(set(p["coc"]         for p in points))
        unique_temp = sorted(set(p["temperature"] for p in points))
        unique_ph   = sorted(set(p["ph"]          for p in points))

        color_labels = {
            "green":  "Protected",
            "yellow": "Caution",
            "red":    "Scale Risk",
            "error":  "No Data",
        }

        return {
            "salt_id":    salt_id,
            "temp_unit":  temp_suffix,
            "axes": {
                "x": {"label": "Cycles of Concentration", "values": unique_coc},
                "y": {"label": f"Temperature ({temp_suffix})",  "values": unique_temp},
                "z": {"label": f"Saturation Index ({salt_id or 'SI'})", "unit": "SI"},
            },
            "color_map":    _COLOUR_HEX,
            "color_labels": color_labels,
            "total_points": len(points),
            "available_salts": sorted(set(
                mineral
                for p in points
                for mineral in (p.get("all_si") or {}).keys()
            )),
            "points":       points,
        }

    # ── STEP: summary counts ─────────────────────────────────────────────────
    @staticmethod
    def _summary(results: List[Dict]) -> Dict[str, int]:
        counts: Dict[str, int] = {"green": 0, "yellow": 0, "red": 0, "error": 0}
        for r in results:
            counts[r.get("color_code", "error")] = counts.get(r.get("color_code", "error"), 0) + 1
        return counts

    # ─────────────────────────────────────────────────────────────────────────
    # ADDITIONAL CALCULATIONS PER GRID POINT
    # ─────────────────────────────────────────────────────────────────────────
    async def _add_calculations_to_results(
        self,
        results: List[Dict[str, Any]],
        raw_water: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """
        For each grid point, calculate LSI, RSI, PSI, CCPP, Mild Steel Corrosion.
        """
        try:
            from app.services.calculation_service import CalculationService
            calc = CalculationService()
        except Exception as e:
            logger.warning(f"CalculationService unavailable: {e}")
            return results

        for r in results:
            try:
                params: Dict[str, Any] = {}
                for k, v in raw_water.items():
                    params[k] = v

                params["pH"]          = {"value": r["_grid_pH"],   "unit": ""}
                params["Temperature"] = {"value": r["_grid_temp"],  "unit": "°C"}

                phreeqc_output = {
                    "ionic_strength":     r.get("ionic_strength", 0.0),
                    "saturation_indices": [
                        {"mineral_name": k, "si_value": v.get("SI", 0.0)}
                        for k, v in r.get("saturation_indices", {}).items()
                    ],
                }

                ionic_strength = r.get("ionic_strength", 0.0)
                calcs: Dict[str, Any] = {}

                try:
                    calcs["lsi"] = await calc.calculate_lsi(params)
                except Exception:
                    pass

                try:
                    calcs["ryznar"] = await calc.calculate_ryznar(params)
                except Exception:
                    pass

                try:
                    calcs["puckorius"] = await calc.calculate_puckorius(params)
                except Exception:
                    pass

                try:
                    calcs["ccpp"] = await calc.calculate_ccpp(phreeqc_output)
                except Exception:
                    pass

                try:
                    calcs["larson_skold"] = await calc.calculate_larson_skold(params)
                except Exception:
                    pass

                try:
                    sat_indices_dict = {
                        item["mineral_name"]: item["si_value"]
                        for item in phreeqc_output["saturation_indices"]
                    }
                    calcs["mild_steel_corrosion"] = await calc.calculate_mild_steel_corrosion(
                        params, sat_indices_dict, do_ppm=5.0,
                        temp_c=r["_grid_temp"]
                    )
                except Exception:
                    pass

                r["calculations"] = calcs

            except Exception as e:
                logger.warning(f"Calculations failed for CoC={r.get('_grid_CoC')}: {e}")
                r["calculations"] = {}

        return results

    # ─────────────────────────────────────────────────────────────────────────
    # PUBLIC: run_analysis
    # ─────────────────────────────────────────────────────────────────────────
    async def run_analysis(self, req: Dict[str, Any]) -> Dict[str, Any]:
        run_id = str(uuid.uuid4())
        logger.info(f"Saturation run started  run_id={run_id}")

        # ── 1. Map dynamic water params ───────────────────────────────────────
        raw_water = req.get("base_water_parameters", {})
        mapped    = _map_water_params(raw_water)
        if not mapped:
            raise ValueError("base_water_parameters could not be mapped to any known ions")

        # ── 2. pH Mode handling ───────────────────────────────────────────────
        # IMPORTANT: adjustment_chemical does NOT modify ion concentrations.
        # It is only used for charge balance ion selection.
        ph_mode  = req.get("ph_mode", "natural")
        fixed_ph = req.get("fixed_ph")

        if ph_mode == "fixed" and fixed_ph is not None:
            try:
                fixed_ph_value = float(fixed_ph)
                mapped["pH"] = {"value": fixed_ph_value, "unit": ""}
                logger.info(f"Fixed pH mode: overriding pH to {fixed_ph_value}")
            except (TypeError, ValueError):
                logger.warning(f"Invalid fixed_ph value '{fixed_ph}' — falling back to natural pH mode")
                ph_mode = "natural"

        # ── 3. Thresholds ─────────────────────────────────────────────────────
        dosage_ppm = float(req.get("dosage_ppm") or 2.0)
        thresholds = _parse_thresholds(req.get("raw_material_chemistry"), dosage_ppm)

        # ── 4. Resolve temperatures ───────────────────────────────────────────
        asset_info = req.get("asset_info") or {}

        cold_temp_raw  = asset_info.get("supplyTemperature") or req.get("temp_min") or 32.2
        cold_temp_unit = asset_info.get("supplyTemperatureType") or req.get("temp_unit") or "°F"
        cold_temp_c    = _to_celsius(float(cold_temp_raw), cold_temp_unit)

        hot_temp_raw   = asset_info.get("returnTemperature") or req.get("temp_max") or 55.0
        hot_temp_unit  = asset_info.get("returnTemperatureType") or req.get("temp_unit") or "°F"
        hot_temp_c     = _to_celsius(float(hot_temp_raw), hot_temp_unit)

        if hot_temp_c < cold_temp_c:
            logger.warning(
                f"Hot temp ({hot_temp_c}°C) < cold temp ({cold_temp_c}°C) — "
                f"likely unit mismatch. Swapping."
            )
            cold_temp_c, hot_temp_c = hot_temp_c, cold_temp_c

        logger.info(f"Temperatures: cold={cold_temp_c}°C, hot={hot_temp_c}°C")

        # ── 5. CO2 factor ─────────────────────────────────────────────────────
        # If ph_mode=fixed, skip CO2 equilibration entirely
        if ph_mode == "fixed":
            co2_factor = None
            logger.info("Fixed pH mode: CO2 equilibration skipped (co2_factor=None)")
        else:
            approach_to_wb = asset_info.get("approachToWB")
            if approach_to_wb is None:
                approach_to_wb = 7.0

            co2_factor = _calculate_co2_factor(
                system_type    = asset_info.get("type") or asset_info.get("systemType"),
                tower_type     = asset_info.get("towerType"),
                fill_type      = asset_info.get("fillType"),
                draft_type     = asset_info.get("draftType"),
                approach_to_wb = float(approach_to_wb),
                co2_override   = req.get("co2_log_partial_pressure"),
            )

        logger.info(f"CO2 factor: {co2_factor} | pH mode: {ph_mode}")

        # ── 6. Resolve balance ions from adjustment_chemical ──────────────────
        # adjustment_chemical is for charge balance only — it does NOT change
        # any ion concentration or affect the pH calculation.
        adjustment_chemical = req.get("adjustment_chemical")
        balance_cation, balance_anion = _resolve_balance_ions(
            adjustment_chemical   = adjustment_chemical,
            balance_cation_override = req.get("balance_cation"),
            balance_anion_override  = req.get("balance_anion"),
        )
        logger.info(
            f"Charge balance: cation={balance_cation}, anion={balance_anion} "
            f"(adjustment_chemical={adjustment_chemical})"
        )

        # ── 7. Build CoC list ─────────────────────────────────────────────────
        coc_min      = float(req.get("coc_min") or 1.0)
        coc_max      = float(req.get("coc_max") or 10.0)
        coc_interval = float(req.get("coc_interval") or 1.0)
        coc_list     = self._build_coc_list(coc_min, coc_max, coc_interval)
        logger.info(f"CoC list: {coc_list}")

        # ── 8. Build evaluation temperature list ──────────────────────────────
        temp_unit = req.get("temp_unit", "F")
        temp_min_raw  = float(req.get("temp_min") or 110.0)
        temp_max_raw  = float(req.get("temp_max") or 160.0)
        temp_interval = float(req.get("temp_interval") or 10.0)

        temp_list_c: List[float] = []
        t = temp_min_raw
        while t <= temp_max_raw + 1e-9:
            temp_list_c.append(_to_celsius(t, temp_unit))
            t += max(temp_interval, 0.1)

        if not temp_list_c:
            temp_list_c = [hot_temp_c]

        logger.info(f"Eval temp list (°C): {temp_list_c}")
        logger.info(f"Grid: {len(coc_list)} CoC × {len(temp_list_c)} Temp = {len(coc_list)*len(temp_list_c)} points")

        # ── 9. Run 2-step PHREEQC pipeline ────────────────────────────────────
        salt_id           = req.get("salt_id")
        salts_of_interest = req.get("salts_of_interest")
        inhibited_salts   = _get_inhibited_salts(req.get("raw_material_chemistry"))
        logger.info(f"Inhibited salts: {inhibited_salts}")

        results, db_used = await self._run_two_step_pipeline(
            mapped_params     = mapped,
            coc_list          = coc_list,
            cold_temp_c       = cold_temp_c,
            temp_list_c       = temp_list_c,
            co2_factor        = co2_factor,
            salt_id           = salt_id,
            salts_of_interest = salts_of_interest,
            thresholds        = thresholds,
            inhibited_salts   = inhibited_salts,
            balance_cation    = balance_cation,
            balance_anion     = balance_anion,
        )

        # ── 10. Add additional calculations per grid point ────────────────────
        results = await self._add_calculations_to_results(results, raw_water)

        # ── 11. Resolve effective salt (case-insensitive) ─────────────────────
        effective_salt = salt_id
        if results:
            sample_si = results[0].get("saturation_indices", {})
            available = list(sample_si.keys())
            logger.info(f"PHREEQC returned {len(available)} minerals: {available[:15]}")

            if salt_id:
                found = any(k.lower() == salt_id.lower() for k in available)
                if not found:
                    logger.warning(f"salt_id '{salt_id}' not found. Available: {available[:10]}. Using first.")
                    effective_salt = available[0] if available else None
                else:
                    effective_salt = next(k for k in available if k.lower() == salt_id.lower())
            else:
                effective_salt = available[0] if available else None

        temp_unit = req.get("temp_unit", "F")
        graph_url = "not-generated"
        try:
            png       = self._generate_graph(results, effective_salt, run_id, temp_unit)
            graph_url = self._upload_s3(png, run_id)
        except Exception as e:
            logger.warning(f"Graph generation/upload failed (non-fatal): {e}")

        # ── 12. Build Plotly-ready graph_data ─────────────────────────────────
        graph_data = self._build_graph_data(results, effective_salt, temp_unit)

        # ── 13. Summary ───────────────────────────────────────────────────────
        summary = self._summary(results)

        # ── 14. Save to DB ────────────────────────────────────────────────────
        doc = {
            "run_id":                  run_id,
            "salt_id":                 effective_salt,
            "salts_of_interest":       salts_of_interest,
            "dosage_ppm":              float(req.get("dosage_ppm") or 2.0),
            "coc_min":                 coc_min,
            "coc_max":                 coc_max,
            "coc_interval":            coc_interval,
            "cold_basin_temp_c":       cold_temp_c,
            "hot_basin_temp_c":        hot_temp_c,
            "temp_unit":               temp_unit,
            "ph_mode":                 ph_mode,
            "fixed_ph":                fixed_ph if ph_mode == "fixed" else None,
            "co2_factor":              co2_factor,
            "adjustment_chemical":     adjustment_chemical,
            "balance_cation":          balance_cation,
            "balance_anion":           balance_anion,
            "database_used":           db_used,
            "total_grid_points":       len(results),
            "grid_results":            results,
            "graph_url":               graph_url,
            "graph_data":              graph_data,
            "summary":                 summary,
            "thresholds":              thresholds,
            "base_water_parameters":   raw_water,
            "product_blend":           req.get("product_blend"),
            "raw_material_chemistry":  req.get("raw_material_chemistry"),
            "asset_info":              asset_info,
            "created_at":              datetime.now(timezone.utc).isoformat(),
        }
        await db.db["saturation_runs"].insert_one(doc)
        logger.info(f"Saturation run saved  run_id={run_id}  summary={summary}")

        return {k: v for k, v in doc.items() if k != "_id"}

    # ─────────────────────────────────────────────────────────────────────────
    # PUBLIC: switch_salt  (re-graph without PHREEQC re-run)
    # ─────────────────────────────────────────────────────────────────────────
    async def switch_salt(self, run_id: str, salt_id: str) -> Dict[str, Any]:
        doc = await db.db["saturation_runs"].find_one({"run_id": run_id})
        if not doc:
            raise ValueError(f"Run not found: {run_id}")

        results    = doc["grid_results"]
        temp_unit  = doc.get("temp_unit", "F")
        thresholds = doc.get("thresholds", {"max_si_at_dose": 0.0, "yellow_lower": -0.5, "yellow_upper": 0.5})

        if not results:
            raise ValueError(f"No grid results saved for run_id: {run_id}")

        sample_si    = results[0].get("saturation_indices", {})
        available    = list(sample_si.keys())
        salt_id_lower = salt_id.lower()

        resolved_salt = None
        for k in available:
            if k.lower() == salt_id_lower:
                resolved_salt = k
                break

        if resolved_salt is None:
            raise ValueError(
                f"Salt '{salt_id}' not found in saved results. "
                f"Available salts: {available[:20]}"
            )

        inhibited_salts = _get_inhibited_salts(doc.get("raw_material_chemistry"))

        for r in results:
            si_info = r["saturation_indices"].get(resolved_salt)
            if si_info is not None:
                si_val = si_info.get("SI", si_info) if isinstance(si_info, dict) else float(si_info)
                r["color_code"] = _color_code_for_salt(
                    float(si_val),
                    resolved_salt,
                    inhibited_salts,
                    thresholds,
                )
            else:
                r["color_code"] = "error"

        chart_data = self._build_chart_data(results, resolved_salt, temp_unit)
        summary    = self._summary(results)

        await db.db["saturation_runs"].update_one(
            {"run_id": run_id},
            {"$set": {
                "active_salt_id": resolved_salt,
                "chart_data":     chart_data,
                "summary":        summary,
            }},
        )

        return {
            "run_id":     run_id,
            "salt_id":    resolved_salt,
            "chart_data": chart_data,
            "summary":    summary,
        }

    # ─────────────────────────────────────────────────────────────────────────
    # PUBLIC: get_available_salts  (PHREEQC mineral list, cached in MongoDB)
    # ─────────────────────────────────────────────────────────────────────────
    async def get_available_salts(self) -> List[Dict[str, str]]:
        cached = await db.get_cached_phreeqc_info("default_v2")
        if cached and cached.get("minerals"):
            return cached["minerals"]

        salts = await self._fetch_salts_from_phreeqc()
        await db.cache_phreeqc_database_info("default_v2", {"minerals": salts})
        return salts

    async def _fetch_salts_from_phreeqc(self) -> List[Dict[str, str]]:
        """
        Fetch ALL minerals/salts from the PHREEQC database.
        """
        salts = self.phreeqc.parse_phases_from_dat_file(self.phreeqc.phreeqc_dat)

        if not salts:
            logger.info("phreeqc.dat yielded no minerals — trying pitzer.dat")
            salts = self.phreeqc.parse_phases_from_dat_file(self.phreeqc.pitzer_dat)

        if salts:
            logger.info(f"✅ Fetched {len(salts)} salts by parsing PHASES section from .dat file")
            return salts

        logger.warning(
            "Direct .dat PHASES parse returned no results — "
            "falling back to PHREEQC simulation (may return incomplete salt list)"
        )
        minimal_params = {
            "pH": 7.0, "Temperature": 25.0,
            "Ca": 100.0, "Mg": 30.0, "Na": 50.0, "K": 5.0,
            "HCO3": 150.0, "SO4": 50.0, "Cl": 50.0, "SiO2": 20.0,
            "Ba": 0.1, "Sr": 0.1, "Fe": 0.1, "F": 0.1,
        }
        try:
            result = await self.phreeqc._run_phreeqc_single(minimal_params, self.phreeqc.phreeqc_dat)
            salts = []
            for item in result.get("saturation_indices", []):
                if isinstance(item, dict):
                    salts.append({
                        "name":             item.get("mineral_name", ""),
                        "chemical_formula": item.get("chemical_formula", ""),
                        "phase":            item.get("phase", ""),
                    })
            logger.info(f"Fallback PHREEQC run returned {len(salts)} salts")
            return salts
        except Exception as e:
            logger.error(f"Failed to fetch salts from PHREEQC fallback run: {e}")
            return []