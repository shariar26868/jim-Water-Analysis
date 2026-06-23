
"""
Saturation Analysis Service  — v4
===================================
Implements client's exact 2-step PHREEQC workflow:

  Step 1-3  (per CoC):
    SOLUTION at cold basin temp + EQUILIBRIUM_PHASES CO2(g)
    → Calculates natural pH after CO2 degassing

  Step 5-6  (per CoC × Temperature):
    SOLUTION at hot evaluation temp, pH from Step 3, Cl charge balance
    → Final SI values used for graph and display

CO2 partial pressure is auto-calculated from tower type:
  Base -3.4 + airflow + fill + draft + approach_to_WB adjustments

Special cases:
  Evaporative Condenser → base -3.4, no correction
  Once Through Cooling  → no EQUILIBRIUM_PHASES at all

FIXES in v4:
  FIX 1: _apply_ph_adjustment — removed _PH_RULES ion modification.
          adjustment_chemical now ONLY drives balance_anion selection.
          Flat ion subtraction (old "HCL" rule) destroyed alkalinity
          and caused PHREEQC to converge to pH ~0.2.
  FIX 2: natural_ph_cache key changed from (coc,) → (coc, cold_temp_c).
          Temperature changes the equilibrium; caching only by CoC
          caused all 15 grid points to share the same broken pH.
  FIX 3: CaCO3 unit conversion added in _convert_caco3_units().
          Inputs like Calcium_as_CaCO3=50 mg/L must be divided by the
          CaCO3/ion MW ratio before passing to PHREEQC (Ca÷2.497,
          Mg÷4.118, HCO3÷1.640).

Public methods:
  run_analysis(request_dict)   → full pipeline
  switch_salt(run_id, salt_id) → re-graph from saved DB data (no re-run)
  get_available_salts()        → PHREEQC mineral list (cached)
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
    "calcium_as_caco3": "Ca",   # will be unit-converted after mapping
    "calcium_as_ca": "Ca",
    # Magnesium
    "magnesium": "Mg", "mg": "Mg",
    "magnesium_as_caco3": "Mg",
    "magnesium_as_mg": "Mg",
    # Sodium
    "sodium": "Na", "na": "Na",
    # Potassium
    "potassium": "K", "k": "K",
    # Chloride
    "chloride": "Cl", "cl": "Cl",
    # Sulfate / Sulphate
    "sulfate": "SO4", "sulphate": "SO4", "so4": "SO4",
    # Alkalinity / Bicarbonate
    "alkalinity": "HCO3", "bicarbonate": "HCO3", "hco3": "HCO3",
    "total_alkalinity": "HCO3", "m_alkalinity": "HCO3",
    "alkalinity_as_caco3": "HCO3",   # unit-converted after mapping
    "alkalinity_as_hco3": "HCO3",
    # Silica
    "silica": "SiO2", "sio2": "SiO2", "silicon": "SiO2",
    "silicon_as_sio2": "SiO2",
    # Barium
    "barium": "Ba", "ba": "Ba",
    # Strontium
    "strontium": "Sr", "sr": "Sr",
    # Iron
    "iron": "Fe", "fe": "Fe",
    "iron_total": "Fe",
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
    "phosphate_total_as_po4": "PO4",
    "phosphate_total_inorganic_as_po4": "PO4",
    "phosphate_ortho_as_po4": "PO4",
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
# FIX 3: CaCO3 → element MW conversion factors
# When a parameter is reported "as CaCO3", divide by this factor to get
# the elemental concentration PHREEQC expects in mg/L as element.
# ─────────────────────────────────────────────────────────────────────────────
_CACO3_CONVERSION_FACTOR: Dict[str, float] = {
    "Ca":   100.086 / 40.078, # 2.497  (CaCO3 MW / Ca MW)
    "Mg":   100.086 / 24.305, # 4.118  (CaCO3 MW / Mg MW)
    "HCO3": 50.045 / 61.0168, # 0.8202 (CaCO3 EqW / HCO3 EqW) - note EqW for monovalent
}

# Keys whose raw_key contains "caco3" → need conversion
_CACO3_ION_KEYS = {"calcium_as_caco3", "magnesium_as_caco3", "alkalinity_as_caco3"}


# Colour hex values
_COLOUR_HEX = {"green": "#2ECC71", "yellow": "#F1C40F", "red": "#E74C3C", "error": "#BDC3C7"}


def _map_water_params(raw: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convert dynamic OCR keys → internal PHREEQC ion keys.
    Preserves unit information for unit-aware PHREEQC input building.
    Returns dict: { ion_key: {"value": float, "unit": str} }

    NOTE: CaCO3 unit conversion is NOT applied here.
    Call _convert_caco3_units() on the result to handle "as CaCO3" inputs.
    """
    out: Dict[str, Any] = {}
    for key, val in raw.items():
        norm = key.lower().replace(" ", "_").replace("-", "_").replace("(", "").replace(")", "").replace("₄","4").replace("₃","3")

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

        out[ion] = {"value": numeric, "unit": unit.strip()}

    return out


def _convert_caco3_units(mapped: Dict[str, Any], raw: Dict[str, Any]) -> Dict[str, Any]:
    """
    FIX 3 — Convert "as CaCO3" reported values to elemental mg/L.

    PHREEQC expects Ca, Mg, HCO3 in mg/L as the element/ion itself.
    Water reports often express these "as CaCO3" (multiply eq weights).

    Conversion:
      Ca   (mg/L as CaCO3) ÷ 2.497  = Ca   (mg/L as Ca)
      Mg   (mg/L as CaCO3) ÷ 4.118  = Mg   (mg/L as Mg)
      HCO3 (mg/L as CaCO3) ÷ 0.820  = HCO3 (mg/L as HCO3)

    Detection: raw key contains "caco3" or "as_caco" (case-insensitive).
    If the same ion appears multiple times (e.g. Calcium_as_CaCO3 AND
    Calcium_as_Ca), the as_Ca form is preferred (it does not need conversion).
    """
    out = dict(mapped)

    # Build a set of ions that were provided WITHOUT the CaCO3 suffix
    # (these take priority and should not be overwritten by a CaCO3 variant)
    ions_as_element: set = set()
    for raw_key in raw.keys():
        norm = raw_key.lower().replace(" ", "_").replace("-", "_")
        if "caco3" not in norm and "as_caco" not in norm:
            ion = _PARAM_ALIAS.get(norm)
            if ion in _CACO3_CONVERSION_FACTOR:
                ions_as_element.add(ion)

    for raw_key, raw_val in raw.items():
        norm = raw_key.lower().replace(" ", "_").replace("-", "_").replace("(","").replace(")","")

        # Only process keys that are "as CaCO3"
        if "caco3" not in norm and "as_caco" not in norm:
            continue

        # Resolve ion key
        stripped = (norm
                    .replace("_as_caco3", "")
                    .replace("_as_caco", "")
                    .replace("as_caco3", "")
                    .replace("as_caco", ""))
        ion = _PARAM_ALIAS.get(stripped) or _PARAM_ALIAS.get(norm)
        if not ion or ion not in _CACO3_CONVERSION_FACTOR:
            continue

        # Don't overwrite if element form already present
        if ion in ions_as_element:
            continue

        # Get numeric value
        if isinstance(raw_val, dict):
            numeric = raw_val.get("value")
            unit = raw_val.get("unit", "mg/L") or "mg/L"
        elif isinstance(raw_val, (int, float)):
            numeric = float(raw_val)
            unit = "mg/L"
        else:
            continue

        if numeric is None:
            continue
        try:
            numeric = float(numeric)
        except (TypeError, ValueError):
            continue

        if numeric <= 0:
            continue

        factor = _CACO3_CONVERSION_FACTOR[ion]
        converted = round(numeric / factor, 4)

        logger.debug(
            f"CaCO3 unit conversion: {raw_key} {numeric} mg/L as CaCO3 "
            f"→ {ion} {converted} mg/L (÷{factor:.4f})"
        )
        out[ion] = {"value": converted, "unit": "mg/L"}

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


def _apply_ph_adjustment(params: Dict[str, Any], chemical: Optional[str]) -> Dict[str, Any]:
    """
    FIX 1 — adjustment_chemical drives ONLY balance_anion selection.

    The old _PH_RULES dict subtracted flat values (e.g. −1.37 from HCO3)
    to simulate acid dosing. This was wrong because:
      - It ignored actual dose amount (ppm)
      - It destroyed alkalinity when HCO3 was low (< 1 mmol/L)
      - PHREEQC then calculated pH ~0.2 from the near-zero buffer water

    The correct approach: leave ion concentrations untouched here.
    PHREEQC Step 1 (CO2 equilibration) will naturally calculate the
    correct post-degassing pH from the actual water chemistry.

    If the user wants a fixed treatment pH, set ph_mode="fixed" and
    provide fixed_ph in the request — that overrides CO2 equilibration.

    The chemical name is used downstream to auto-select balance_anion:
      HCl  → Cl
      H2SO4 → SO4
      NaOH → Na (balance_cation)
    """
    if chemical:
        logger.info(
            f"adjustment_chemical='{chemical}' noted for charge balance selection. "
            f"Ion concentrations are NOT modified (FIX 1)."
        )
    return dict(params)


def _resolve_balance_ion_from_chemical(
    chemical: Optional[str],
    explicit_balance_anion: Optional[str],
    explicit_balance_cation: Optional[str],
) -> Tuple[str, str]:
    """
    Auto-resolve balance_anion / balance_cation from adjustment_chemical.

    PHREEQC charge balance rules (strict):
      Valid anions:  Cl, SO4  (HCO3/Alkalinity NEVER valid — circular dependency)
      Valid cations: Na, K    (Ca, Mg NEVER valid — they are part of carbonate system)

    Returns (balance_cation, balance_anion).
    """
    # ── Step 1: Start with explicit values (or defaults) ─────────────────────
    raw_cation = (explicit_balance_cation or "Na").strip()
    raw_anion  = (explicit_balance_anion  or "Cl").strip()

    # ── Step 2: Validate & normalize anion ───────────────────────────────────
    # HCO3, Alkalinity, CO3, etc. are NEVER valid charge balance anions in PHREEQC.
    # They create circular dependency in the carbonate system → convergence failure.
    norm_anion = raw_anion.upper().replace("-", "").replace("(", "").replace(")", "").replace(" ", "")
    if "SO4" in norm_anion or norm_anion in ("S6", "S(6)", "SULFATE", "SULPHATE"):
        balance_anion = "SO4"
    elif norm_anion in ("CL", "CHLORIDE", "HCL"):
        balance_anion = "Cl"
    else:
        # HCO3, ALKALINITY, CO3, HCO3-, etc. → default to Cl
        if norm_anion not in ("CL", "SO4"):
            logger.warning(
                f"balance_anion='{raw_anion}' is not a valid PHREEQC charge balance anion "
                f"(HCO3/Alkalinity creates circular dependency). Defaulting to 'Cl'."
            )
        balance_anion = "Cl"

    # ── Step 3: Validate & normalize cation ──────────────────────────────────
    # Ca, Mg are NOT valid PHREEQC charge balance cations.
    norm_cation = raw_cation.upper().replace("+", "").replace("2", "").replace(" ", "")
    if norm_cation == "K":
        balance_cation = "K"
    elif norm_cation in ("NA", "SODIUM"):
        balance_cation = "Na"
    else:
        # Ca, Mg, Fe, etc. → default to Na
        if norm_cation not in ("NA", "K"):
            logger.warning(
                f"balance_cation='{raw_cation}' is not a valid PHREEQC charge balance cation "
                f"(only Na or K allowed). Defaulting to 'Na'."
            )
        balance_cation = "Na"

    # ── Step 4: Override from adjustment_chemical if provided ────────────────
    if chemical:
        chem = chemical.upper().replace("-", "").replace("_", "").replace(" ", "")
        if chem in ("HCL", "HYDROCHLORIC", "HYDROCHLORICACID"):
            balance_anion = "Cl"
        elif chem in ("H2SO4", "SULFURIC", "SULPHURIC", "SULFURICACID"):
            balance_anion = "SO4"
        elif chem in ("NAOH", "SODIUMHYDROXIDE", "CAUSTIC", "CAUSTICODA"):
            balance_cation = "Na"
            # keep balance_anion as already resolved
        elif chem in ("CA(OH)2", "CAOH2", "LIME", "CALCIUMHYDROXIDE", "CALCIUMHYDROXIDE"):
            # Ca(OH)2 → Na is the valid cation (Ca is NOT valid for charge balance)
            balance_cation = "Na"

    logger.info(
        f"Charge balance resolved: chemical='{chemical}', "
        f"explicit_anion='{raw_anion}'→'{balance_anion}', "
        f"explicit_cation='{raw_cation}'→'{balance_cation}'"
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


# Mineral → required ions mapping (subset of common minerals)
# If a mineral's required ion is missing from water, PHREEQC won't calculate its SI
_MINERAL_REQUIRED_IONS: Dict[str, List[str]] = {
    "Fluorite":       ["F"],
    "Fluorapatite":   ["F", "PO4"],
    "Strengite":      ["Fe", "PO4"],
    "Vivianite":      ["Fe", "PO4"],
    "Siderite":       ["Fe"],
    "Goethite":       ["Fe"],
    "Ferrihydrite":   ["Fe"],
    "Hematite":       ["Fe"],
    "Magnetite":      ["Fe"],
    "Pyrite":         ["Fe"],
    "Rhodochrosite":  ["Mn"],
    "Pyrolusite":     ["Mn"],
    "Manganite":      ["Mn"],
    "Barite":         ["Ba"],
    "Witherite":      ["Ba"],
    "Celestite":      ["Sr"],
    "Strontianite":   ["Sr"],
    "Hydroxyapatite": ["PO4"],
    "Strengite":      ["Fe", "PO4"],
    "Variscite":      ["Al", "PO4"],
    "Gibbsite":       ["Al"],
    "Boehmite":       ["Al"],
    "Diaspore":       ["Al"],
    "Kaolinite":      ["Al", "SiO2"],
    "Albite":         ["Na", "Al", "SiO2"],
    "Anorthite":      ["Ca", "Al", "SiO2"],
    "K-feldspar":     ["K", "Al", "SiO2"],
    "Illite":         ["K", "Al", "SiO2"],
    "Montmorillonite":["Al", "SiO2"],
    "Chrysotile":     ["Mg", "SiO2"],
    "Talc":           ["Mg", "SiO2"],
    "Sepiolite":      ["Mg", "SiO2"],
    "Chalcedony":     ["SiO2"],
    "Quartz":         ["SiO2"],
    "Amorphous silica":["SiO2"],
    "SiO2(a)":        ["SiO2"],
}

# Ion display names for user-friendly messages
_ION_DISPLAY_NAMES: Dict[str, str] = {
    "F":    "Fluoride (F⁻)",
    "Fe":   "Iron (Fe)",
    "Mn":   "Manganese (Mn)",
    "Ba":   "Barium (Ba)",
    "Sr":   "Strontium (Sr)",
    "PO4":  "Phosphate (PO₄)",
    "Al":   "Aluminum (Al)",
    "SiO2": "Silica (SiO₂)",
    "Na":   "Sodium (Na)",
    "K":    "Potassium (K)",
    "Ca":   "Calcium (Ca)",
    "Mg":   "Magnesium (Mg)",
    "Cl":   "Chloride (Cl⁻)",
    "SO4":  "Sulfate (SO₄²⁻)",
    "HCO3": "Alkalinity (HCO₃⁻)",
}


def _get_unavailable_salts_with_reasons(
    all_requested_salts: List[str],
    available_salts: List[str],
    mapped_water_params: Dict[str, Any],
) -> List[Dict[str, str]]:
    """
    For salts that were requested but not returned by PHREEQC,
    explain WHY they are unavailable (which ions are missing).

    Returns list of:
      { "salt": "Fluorite", "reason": "Not available — Fluoride (F⁻) not in water sample" }
    """
    available_lower = {s.lower() for s in available_salts}
    present_ions = {k for k, v in mapped_water_params.items()
                    if v is not None and (
                        (isinstance(v, dict) and float(v.get("value", 0)) > 0)
                        or (isinstance(v, (int, float)) and float(v) > 0)
                    )}

    unavailable = []
    for salt in (all_requested_salts or []):
        if salt.lower() in available_lower:
            continue  # available, skip

        # Find missing ions
        required = _MINERAL_REQUIRED_IONS.get(salt, [])
        missing = [ion for ion in required if ion not in present_ions]

        if missing:
            missing_names = ", ".join(_ION_DISPLAY_NAMES.get(m, m) for m in missing)
            reason = f"Not available — {missing_names} not in water sample"
        else:
            reason = (
                "Not available — PHREEQC did not calculate SI for this mineral "
                "(may not be in database or insufficient ions)"
            )

        unavailable.append({"salt": salt, "reason": reason})

    return unavailable


# ─────────────────────────────────────────────────────────────────────────────
# CO2 PARTIAL PRESSURE CALCULATOR
# ─────────────────────────────────────────────────────────────────────────────

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
#     if co2_override is not None:
#         return co2_override

#     sys = (system_type or "").lower().strip()

#     if "once" in sys and "through" in sys:
#         return None

#     if "evaporative" in sys or "condenser" in sys:
#         return -3.4

#     base = -3.4

#     airflow_key = (tower_type or "").lower().strip()
#     base += _CO2_AIRFLOW_ADJ.get(airflow_key, 0.0)

#     fill_key = (fill_type or "").lower().strip()
#     base += _CO2_FILL_ADJ.get(fill_key, 0.0)

#     draft_key = (draft_type or "").lower().strip()
#     base += _CO2_DRAFT_ADJ.get(draft_key, 0.0)

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

def _calculate_co2_factor(
    system_type: Optional[str],
    tower_type: Optional[str],
    fill_type: Optional[str],
    draft_type: Optional[str],
    approach_to_wb: Optional[float],
    co2_override: Optional[float],
) -> Optional[float]:
    """
    CO2(g) log partial pressure for EQUILIBRIUM_PHASES.
    Always returns -3.4 (atmospheric baseline).
    Only exception: Once Through Cooling → returns None.
    """
    if co2_override is not None:
        return co2_override

    sys = (system_type or "").lower().strip()

    if "once" in sys and "through" in sys:
        return None

    logger.info("CO2 factor: -3.4 (fixed atmospheric baseline)")
    return -3.4


def _f_to_c(f: float) -> float:
    """Fahrenheit to Celsius."""
    return round((f - 32) * 5 / 9, 2)


def _to_celsius(value: float, unit: str) -> float:
    """Convert temperature to Celsius."""
    u = (unit or "").strip().upper()
    if u in ("F", "°F"):
        return _f_to_c(value)
    return round(value, 2)


def _robust_safe_float(val: Any, default: float = 0.0) -> float:
    """
    Robust float conversion helper.
    Cleans up common unit suffixes, commas, and percentage signs.
    """
    if val is None:
        return default
    if isinstance(val, (int, float)):
        return float(val)
    try:
        clean_val = str(val).strip().replace("%", "")
        # Remove commas
        clean_val = clean_val.replace(",", "")
        # Extract first space-separated token (handles "1000 GPM" or "120 F")
        tokens = clean_val.split()
        if tokens:
            clean_val = tokens[0]
        return float(clean_val)
    except (TypeError, ValueError, IndexError):
        return default


# ─────────────────────────────────────────────────────────────────────────────
# CYCLED WATER PARAMETERS BUILDER
# Builds the concentrated water chemistry table for a specific CoC × Temp point.
# This is shown in the frontend when a user clicks a bar on the 3D graph.
# ─────────────────────────────────────────────────────────────────────────────

def _build_cycled_water_params(
    mapped_params: Dict[str, Any],
    coc: float,
    temp_display: float,
    temp_c: float,
    natural_ph: float,
    desc: Dict[str, Any],
    do_ppm: float,
) -> Dict[str, Any]:
    """
    Build the "Cycled Water Parameters" table for a specific grid point.

    Shows the concentrated water chemistry at CoC × Temp:
      - All ion concentrations = base_water × CoC
      - pH = natural pH from CO2 equilibration (Step 1)
      - Temperature = evaluation temperature

    Ion display order matches PHREEQC SOLUTION block convention.
    """
    def _get_conc(ion: str) -> Optional[float]:
        """Get base value from mapped_params and multiply by CoC."""
        v = mapped_params.get(ion)
        if v is None:
            return None
        base = float(v.get("value", 0) if isinstance(v, dict) else v)
        if base <= 0:
            return None
        return round(base * coc, 4)

    def _get_unit(ion: str) -> str:
        v = mapped_params.get(ion)
        if isinstance(v, dict):
            return v.get("unit", "mg/L") or "mg/L"
        return "mg/L"

    # Build parameter rows in display order
    params: Dict[str, Any] = {}

    # pH (natural pH from CO2 equilibration — not multiplied by CoC)
    params["pH"] = {
        "value": round(natural_ph, 3),
        "unit": "",
        "label": "pH",
    }

    # Ion map: internal key → display label, PHREEQC name, as-unit
    # Matches PHREEQC SOLUTION block display order
    ion_display = [
        ("Ca",   "Calcium",      "Ca",          "CaCO3"),
        ("Mg",   "Magnesium",    "Mg",          "CaCO3"),
        ("Na",   "Sodium",       "Na",          "Na"),
        ("K",    "Potassium",    "K",           "K"),
        ("HCO3", "Alkalinity",   "Alkalinity",  "CaCO3"),
        ("Cl",   "Chloride",     "Cl",          "Cl"),
        ("SO4",  "Sulfate",      "S(6)",        "SO4"),
        ("SiO2", "Silica",       "Si",          "SiO2"),
        ("Fe",   "Iron",         "Fe",          "Fe2O3"),
        ("PO4",  "Phosphate",    "P",           "PO4"),
        ("Ba",   "Barium",       "Ba",          "Ba"),
        ("Sr",   "Strontium",    "Sr",          "Sr"),
        ("Mn",   "Manganese",    "Mn",          "Mn"),
        ("F",    "Fluoride",     "F",           "F"),
        ("Zn",   "Zinc",         "Zn",          "Zn"),
        ("Cu",   "Copper",       "Cu",          "Cu"),
        ("Pb",   "Lead",         "Pb",          "Pb"),
        ("NO3",  "Nitrate",      "N(5)",        "NO3"),
    ]

    # CaCO3 conversion factors (elemental mg/L → as CaCO3 mg/L)
    _TO_CACO3 = {
        "Ca":  100.09 / 40.08,   # Ca elemental → CaCO3
        "Mg":  100.09 / 24.31,   # Mg elemental → CaCO3
        "HCO3": 100.09 / 61.02,  # HCO3 → CaCO3 (if not already as CaCO3)
    }

    # Identify which ion is the charge balance ion (from mapped_params metadata)
    charge_ion = mapped_params.get("_balance_anion") or mapped_params.get("_balance_cation")

    for ion_key, label, phreeqc_name, as_unit in ion_display:
        conc = _get_conc(ion_key)
        if conc is not None:
            unit = _get_unit(ion_key)
            is_charge_balance = (ion_key == charge_ion)

            # Convert to display unit if needed
            display_value = conc
            display_unit = "ppm"

            if ion_key in ("Ca", "Mg"):
                # mapped_params has elemental mg/L — convert to as CaCO3 for display
                unit_raw = unit.lower()
                if "caco3" not in unit_raw:
                    display_value = round(conc * _TO_CACO3[ion_key], 4)
                else:
                    display_value = conc
                display_unit = "ppm"
                as_unit = "CaCO3"

            elif ion_key == "HCO3":
                # Show as CaCO3 ppm
                unit_raw = unit.lower()
                if "caco3" not in unit_raw:
                    display_value = round(conc * _TO_CACO3["HCO3"], 4)
                else:
                    display_value = conc
                display_unit = "ppm"
                as_unit = "CaCO3"

            elif ion_key == "Fe":
                # Fe as Fe2O3: multiply by (159.69 / 2 / 55.845)
                display_value = round(conc * (159.69 / 2 / 55.845), 4)
                display_unit = "ppm"
                as_unit = "Fe2O3"

            else:
                display_unit = "ppm"

            params[ion_key] = {
                "value":          display_value,
                "unit":           display_unit,
                "as":             as_unit,
                "phreeqc_name":   phreeqc_name,
                "label":          label,
                "charge_balance": is_charge_balance,
            }

    # Dissolved Oxygen
    params["DO"] = {
        "value": do_ppm,
        "unit":  "ppm",
        "label": "Dissolved Oxygen",
    }

    # Solution properties from PHREEQC description_of_solution
    solution_props = {
        "specific_conductance": {
            "value": desc.get("specific_conductance"),
            "unit":  "µS/cm",
            "label": "Specific Conductance",
        },
        "density": {
            "value": desc.get("density"),
            "unit":  "g/cm³",
            "label": "Density",
        },
        "activity_of_water": {
            "value": desc.get("activity_of_water"),
            "unit":  "",
            "label": "Activity of Water",
        },
        "ionic_strength": {
            "value": desc.get("ionic_strength_desc"),
            "unit":  "mol/kgw",
            "label": "Ionic Strength",
        },
        "mass_of_water_kg": {
            "value": desc.get("mass_of_water_kg"),
            "unit":  "kg",
            "label": "Mass of Water",
        },
    }

    return {
        "coc":             coc,
        "temperature_c":   round(temp_c, 2),
        "pH":              round(natural_ph, 3),
        "units":           "mg/L",
        "parameters":      params,
        "solution_properties": {k: v for k, v in solution_props.items() if v["value"] is not None},
    }


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
            if k in skip_keys or k.startswith("_"):
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
            if k in skip_keys or k.startswith("_"):
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
        temp_list_raw: List[float],
        co2_factor: Optional[float],
        balance_cation: str,
        balance_anion: str,
    ) -> Tuple[List[Dict[str, Any]], str]:
        """
        Client pseudo-code:
          Do CurrentTemp = temp_min to temp_max
            Do CoC = coc_min to coc_max
              Step 1: supply_temp + CO2 eq → natural pH  (cached by CoC × cold_temp)
              Step 2: CurrentTemp + natural pH + charge balance → SI
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

        results: List[Dict[str, Any]] = []

        # FIX 2: cache key is (coc, cold_temp_c) — NOT just coc.
        # Step 1 depends on cold basin temp; if that ever varies per grid
        # point in the future this cache remains correct.
        natural_ph_cache: Dict[Tuple[float, float], float] = {}

        total = len(temp_list_c) * len(coc_list)
        done  = 0

        for hot_temp_c, hot_temp_raw in zip(temp_list_c, temp_list_raw):
            for coc in coc_list:
                done += 1
                logger.info(f"[{done}/{total}] CoC={coc}, eval_temp={hot_temp_c}°C (raw={hot_temp_raw}) ...")

                # ── Step 1: natural pH at cold supply temp (cached per CoC × cold_temp) ──
                cache_key = (coc, cold_temp_c)
                if cache_key not in natural_ph_cache:
                    natural_ph = await self._step1_natural_ph(
                        mapped_params, coc, cold_temp_c, co2_factor, database
                    )
                    natural_ph_cache[cache_key] = natural_ph
                    logger.debug(f"  Cached natural_ph={natural_ph:.3f} for key={cache_key}")
                else:
                    natural_ph = natural_ph_cache[cache_key]

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

                desc = phreeqc_result.get("description_of_solution", {})

                # ── DO Level — standard DO saturation formula ─────────────────
                # Uses the standard polynomial DO saturation formula (APHA/AWWA):
                #   DO_sat(T) = 14.62 - 0.3898×T + 0.006969×T² - 0.00005896×T³
                # This is valid across the full temperature range (0–65°C).
                #
                # If wet bulb temp is available, apply evaporative correction:
                #   DO = DO_sat - 0.05 × (T_water - T_wetbulb)
                #
                # NOTE: PHREEQC O2 molality is NOT used because pe=4.0 gives
                # near-zero O2 (reducing conditions) — not realistic for cooling water.
                dist_species = phreeqc_result.get("distribution_of_species", {})
                do_ppm = 6.0  # default
                try:
                    tw_c = hot_temp_c  # evaluation temperature in °C
                    # Standard DO saturation at temperature T (APHA polynomial)
                    do_sat = (14.62
                              - 0.3898 * tw_c
                              + 0.006969 * tw_c ** 2
                              - 0.00005896 * tw_c ** 3)
                    do_sat = max(do_sat, 0.5)  # physical minimum ~0.5 ppm at very high temps

                    # Apply wet-bulb evaporative correction if available
                    wb_raw = mapped_params.get("_wet_bulb_temp_c")
                    if wb_raw is not None:
                        twb_c = float(wb_raw)
                        correction = 0.05 * (tw_c - twb_c)
                        do_ppm = round(max(0.5, do_sat - correction), 4)
                    else:
                        do_ppm = round(do_sat, 4)
                except Exception:
                    do_ppm = 6.0

                results.append({
                    "_grid_CoC":               coc,
                    "_grid_temp":              round(hot_temp_raw, 2),
                    "_grid_temp_c":            hot_temp_c,
                    "_grid_pH":                natural_ph,
                    "_cold_temp_c":            cold_temp_c,
                    "_natural_ph_at_cold":     natural_ph,
                    "saturation_indices":      si_detail,
                    "description_of_solution": desc,
                    "distribution_of_species": dist_species,
                    "dissolved_oxygen_ppm":    do_ppm,   # per-CoC DO value
                    "color_code":              "green",
                    "per_salt_colors":         {},
                    "ionic_strength":          phreeqc_result.get("ionic_strength", 0.0),
                    "charge_balance_error_pct": phreeqc_result.get("charge_balance_error_pct", 0.0),
                    "electrical_balance":      phreeqc_result.get("electrical_balance", 0.0),
                    "specific_conductance":    desc.get("specific_conductance"),
                    "density":                 desc.get("density"),
                    # ── Cycled Water Parameters (for frontend table on bar click) ──
                    # Shows the concentrated water chemistry at this CoC × Temp point.
                    # Values = base_water × CoC (except pH and Temperature).
                    "cycled_water_parameters": _build_cycled_water_params(
                        mapped_params, coc, hot_temp_raw, hot_temp_c, natural_ph,
                        desc, do_ppm
                    ),
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

        max_abs_si = max([abs(z) for z in z_vals]) if len(z_vals) > 0 else 1.0
        if max_abs_si == 0:
            max_abs_si = 1.0
        opacities = [0.3 + 0.7 * (abs(z) / max_abs_si) for z in z_vals]

        # _grid_temp already stores the user's original unit value (F or C)
        y_label = f"Temperature ({'°F' if temp_unit.upper() == 'F' else '°C'})"
        y_display = y_vals

        fig = plt.figure(figsize=(13, 8), facecolor="#1A1A2E")
        ax  = fig.add_subplot(111, projection="3d", facecolor="#16213E")

        unique_x = sorted(set(x_vals))
        unique_y = sorted(set(y_display))
        dx = max(0.3, (max(unique_x) - min(unique_x)) / max(len(unique_x), 1) * 0.7) if len(unique_x) > 1 else 0.5
        dy = max(1.5, (max(unique_y) - min(unique_y)) / max(len(unique_y), 1) * 0.7) if len(unique_y) > 1 else 5.0

        for xi, yi, zi, color, opacity in zip(x_vals, y_display, z_vals, colors, opacities):
            dz = abs(zi) if zi != 0 else 0.01
            z_bottom = min(zi, 0.0)
            ax.bar3d(xi - dx/2, yi - dy/2, z_bottom, dx, dy, dz,
                     color=color, alpha=opacity, shade=True)

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

    # ── STEP: build graph_data JSON ──────────────────────────────────────────
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

        si_vals = []
        for r in results:
            val = _get_si(r["saturation_indices"], salt_id)
            si_vals.append(val if val is not None else 0.0)
            
        max_abs_si = max([abs(s) for s in si_vals]) if si_vals else 1.0
        if max_abs_si == 0:
            max_abs_si = 1.0

        bars = []
        for r, si_val in zip(results, si_vals):
            # _grid_temp already stores the user's original unit value (no conversion needed)
            temp_display = round(r["_grid_temp"], 1)
            
            opacity = round(0.3 + 0.7 * (abs(si_val) / max_abs_si), 3)

            all_si = {}
            for mineral, info in r["saturation_indices"].items():
                if isinstance(info, dict):
                    _si = info.get("SI")
                    # SR may already be stored; if not, derive it from SI
                    _sr = info.get("SR") if info.get("SR") is not None else (
                        round(10 ** _si, 6) if _si is not None else None
                    )
                    all_si[mineral] = {
                        "SI":               _si,
                        "SR":               _sr,
                        "log_IAP":          info.get("log_IAP"),
                        "log_K":            info.get("log_K"),
                        "chemical_formula": info.get("chemical_formula"),
                        "phase":            info.get("phase"),
                    }
                else:
                    _si = float(info)
                    all_si[mineral] = {
                        "SI": _si,
                        "SR": round(10 ** _si, 6),
                    }

            desc = r.get("description_of_solution") or {}

            # SR = 10^SI (always positive — alternative for frontends that can't render negative bars)
            sr_val = round(10 ** si_val, 4) if si_val is not None else None

            r["bar_data"] = {
                "color_hex": _COLOUR_HEX.get(r["color_code"], "#BDC3C7"),
                "opacity": opacity,
                "sr_color": "green" if (sr_val is not None and sr_val < 1) else "red",
                "sr_color_hex": _COLOUR_HEX.get("green") if (sr_val is not None and sr_val < 1) else _COLOUR_HEX.get("red"),
            }

            bars.append({
                "x":         r["_grid_CoC"],
                "y":         si_val,          # SI (can be negative)
                "y_sr":      sr_val,           # SR = 10^SI (always positive, < 1 = no scale, ≥ 1 = scale)
                "z":         temp_display,
                "color":     r["color_code"],
                "color_hex": _COLOUR_HEX.get(r["color_code"], "#BDC3C7"),
                "sr_color":  "green" if (sr_val is not None and sr_val < 1) else "red",
                "sr_color_hex": _COLOUR_HEX.get("green") if (sr_val is not None and sr_val < 1) else _COLOUR_HEX.get("red"),
                "opacity":   opacity,
                "click_data": {
                    "CoC":              r["_grid_CoC"],
                    "pH":               r["_grid_pH"],
                    "temperature":      temp_display,
                    "temperature_unit": "°F" if temp_unit.upper() == "F" else "°C",
                    "selected_salt":    salt_id,
                    "name":             salt_id or "",
                    "SI":               si_val,
                    "SR":               sr_val,
                    "status":           color_labels.get(r["color_code"], r["color_code"]),
                    "ionic_strength":   r.get("ionic_strength"),
                    "charge_balance_error_pct": r.get("charge_balance_error_pct"),
                    "density":          desc.get("density"),
                    "activity_of_water": desc.get("activity_of_water"),
                    "all_saturation_indices": all_si,
                },
                "tooltip": {
                    "CoC":              r["_grid_CoC"],
                    "pH":               r["_grid_pH"],
                    "SI":               si_val,
                    "SR":               sr_val,
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

        def _make_bar_mesh(x_center, z_center, y_top, color_hex, opacity, dx=0.4, dz=4.0):
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
                "opacity":    opacity,
                "flatshading": True,
                "showscale":  False,
                "lighting":   {"ambient": 0.6, "diffuse": 0.8, "specular": 0.3},
            }

        # Define axis values for plotly layout ranges
        x_vals = unique_coc
        y_vals = [b["y"] if b["y"] is not None else 0.0 for b in bars]
        z_vals = unique_temp

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
                opacity=bar["opacity"],
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
                    f"<b>SI ({salt_id or 'SI'}):</b> {si:.4f}<br>"
                    f"<b>Status:</b> {cd['status']}"
                    "<extra></extra>"
                ),
                "showlegend": False,
            })

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

    # ── STEP: enrich each grid point ─────────────────────────────────────────
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
        # dosage_ppm: user-provided value, ensure proper float conversion
        _dosage_raw = req.get("dosage_ppm")
        try:
            dosage_ppm = float(_dosage_raw) if _dosage_raw is not None else 2.0
        except (TypeError, ValueError):
            dosage_ppm = 2.0
        temp_unit        = req.get("temp_unit", "C")

        recirc_rate_gpm  = _robust_safe_float(asset_info.get("recirculationRate"), 0.0)
        hot_temp_f       = _robust_safe_float(asset_info.get("hotWaterTempF"), 0.0)
        cold_temp_f      = _robust_safe_float(asset_info.get("coldWaterTempF"), 0.0)
        wet_bulb_f       = _robust_safe_float(asset_info.get("wetBulbTempF"), 0.0)
        drift_pct        = _robust_safe_float(asset_info.get("driftPercent"), 0.1)
        evap_factor      = _robust_safe_float(asset_info.get("evaporationFactorPercent"), 85.0)
        metallurgy       = asset_info.get("systemMetallurgy") or []

        product_cost_per_lb = _robust_safe_float(product_blend.get("costPerLb"), 0.0)
        # Product name: prefer product_blend.productName, fallback to raw_material commonName
        product_name = (
            product_blend.get("productName")
            or (raw_mat.get("commonName") if raw_mat else None)
            or (raw_mat.get("rawMaterialId") if raw_mat else None)
            or "Product"
        )

        # Build a mapped (normalized) version of base_water_parameters for calc_svc
        _mapped_base = _map_water_params(base_water_parameters)
        _mapped_base = _convert_caco3_units(_mapped_base, base_water_parameters)

        enriched = []
        for r in results:
            coc      = r["_grid_CoC"]
            temp_c   = r.get("_grid_temp_c", r["_grid_temp"])  # use Celsius for calcs
            ph       = r["_grid_pH"]
            ionic_s  = r.get("ionic_strength", 0.0)

            # Build conc_params with both raw keys AND normalized ion keys
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

            # Add normalized ion keys (Ca, Mg, HCO3, Cl, SO4, etc.) scaled by CoC
            # These are what calculation_service.py actually looks for
            _ION_ALIASES = {
                "Ca":   ["Calcium", "calcium"],
                "Mg":   ["Magnesium", "magnesium"],
                "Na":   ["Sodium", "sodium"],
                "K":    ["Potassium", "potassium"],
                "Cl":   ["Chloride", "chloride"],
                "SO4":  ["Sulfate", "Sulphate", "sulfate", "sulphate"],
                "HCO3": ["Alkalinity", "Bicarbonate", "alkalinity", "bicarbonate"],
                "SiO2": ["Silica", "Silicon", "silica"],
                "Fe":   ["Iron", "iron"],
                "PO4":  ["Phosphate", "phosphate"],
                "Ba":   ["Barium", "barium"],
                "Sr":   ["Strontium", "strontium"],
            }
            for ion_key, aliases in _ION_ALIASES.items():
                if ion_key in _mapped_base:
                    base_val = _mapped_base[ion_key]
                    base_num = float(base_val.get("value", 0) if isinstance(base_val, dict) else base_val)
                    scaled   = round(base_num * coc, 4)
                    # ✅ FIX: Preserve unit information from _mapped_base for unit-aware calculations
                    entry    = {"value": scaled, "unit": base_val.get("unit", "mg/L") if isinstance(base_val, dict) else "mg/L"}
                    # Add under normalized key (e.g. "Ca")
                    conc_params[ion_key] = entry
                    # Add under human-friendly aliases (e.g. "Calcium") if not already present
                    for alias in aliases:
                        if alias not in conc_params:
                            conc_params[alias] = entry

            # Estimate TDS from ion sum (needed by PSI/LSI when TDS not in water params)
            _tds_ions = ["Ca", "Mg", "Na", "K", "Cl", "SO4", "HCO3", "SiO2", "Fe", "Ba", "Sr"]
            _tds_sum = sum(
                float(conc_params[ion].get("value", 0) if isinstance(conc_params[ion], dict) else conc_params[ion])
                for ion in _tds_ions if ion in conc_params
            )
            if "TDS" not in conc_params and _tds_sum > 0:
                conc_params["TDS"] = {"value": round(_tds_sum, 2), "unit": "mg/L"}

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
                except Exception:
                    indices["lsi"] = {"lsi": None, "interpretation": "N/A", "risk": "N/A", "note": "Requires Calcium and Alkalinity in water sample"}

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
                except Exception:
                    indices["ryznar"] = {"ri": None, "interpretation": "N/A", "risk": "N/A", "note": "Requires Calcium and Alkalinity in water sample"}

            try:
                indices["puckorius"] = await calc_svc.calculate_puckorius(conc_params)
            except Exception:
                indices["puckorius"] = {"index": None, "interpretation": "N/A", "risk": "N/A", "note": "Requires Calcium and Alkalinity in water sample"}

            try:
                indices["larson_skold"] = await calc_svc.calculate_larson_skold(conc_params)
            except Exception:
                indices["larson_skold"] = {"index": None, "interpretation": "N/A", "risk": "N/A", "note": "Requires Cl, SO4, and Alkalinity in water sample"}

            try:
                indices["stiff_davis"] = await calc_svc.calculate_stiff_davis(conc_params, ionic_s)
            except Exception:
                indices["stiff_davis"] = {"index": None, "interpretation": "N/A", "risk": "N/A", "note": "Requires Calcium and Alkalinity in water sample"}

            eq_phases = r.get("equilibrium_phases", {})
            calcite_moles = eq_phases.get("Calcite")
            if calcite_moles is not None:
                ccpp_ppm = round(calcite_moles * 100.09 * 1000, 2)
            elif calcite_si is not None:
                # Use normalized Ca from _mapped_base (handles CaCO3 conversion)
                ca_base = _get_ion_value(_mapped_base, "Ca") or 0.0
                ca_val  = ca_base * coc
                ca_as_caco3 = ca_val * (100.09 / 40.08)
                ccpp_ppm = round(calcite_si * ca_as_caco3 / 10, 2) if ca_as_caco3 > 0 else None
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
        requested_salts: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Build frontend-ready structured data for interactive 3D bar chart.
        requested_salts: the salts the user selected — available_salts will only show these.
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

        def _build_corrosion_for_point(pt: Dict) -> Dict:
            """
            Return a merged corrosion dict for one grid point.
            Priority: r["corrosion"] (from _enrich_grid_points, most detailed)
            Fallback:  r["calculations"]["*_corrosion"] (from _add_calculations_to_results)
            Covers: mild_steel, copper, admiralty_brass
            """
            corr = dict(pt.get("corrosion") or {})
            calcs = pt.get("calculations") or {}

            def _fmt(ms: Dict, risk_label: str = None) -> Dict:
                return {
                    "cr_mpy":                   ms.get("cr_mpy"),
                    "cr_base_mpy":              ms.get("cr_base_mpy"),
                    "total_inhibition_percent": ms.get("total_inhibition_percent"),
                    "rating":                   ms.get("rating"),
                    "risk_level":               risk_label or ms.get("rating"),
                    "do_ppm_used":              ms.get("do_ppm_used") or (ms.get("components") or {}).get("do_ppm"),
                    "components":               ms.get("components"),
                    "note":                     ms.get("note"),
                    "source":                   "calculations",
                }

            if "mild_steel" not in corr and "mild_steel_corrosion" in calcs:
                corr["mild_steel"] = _fmt(calcs["mild_steel_corrosion"])

            if "copper" not in corr and "copper_corrosion" in calcs:
                corr["copper"] = _fmt(calcs["copper_corrosion"])

            if "admiralty_brass" not in corr and "admiralty_brass_corrosion" in calcs:
                corr["admiralty_brass"] = _fmt(calcs["admiralty_brass_corrosion"])

            return corr

        si_vals = []
        for r in results:
            val = _get_si(r["saturation_indices"], salt_id)
            si_vals.append(val if val is not None else 0.0)
            
        max_abs_si = max([abs(s) for s in si_vals]) if si_vals else 1.0
        if max_abs_si == 0:
            max_abs_si = 1.0

        points = []
        for r, si_val in zip(results, si_vals):
            # _grid_temp already stores the user's original unit value (no conversion needed)
            temp_display = round(r["_grid_temp"], 2)
            desc   = r.get("description_of_solution") or {}
            
            opacity = round(0.3 + 0.7 * (abs(si_val) / max_abs_si), 3)

            all_si = {}
            for mineral, info in r["saturation_indices"].items():
                if isinstance(info, dict):
                    _si = info.get("SI")
                    _sr = info.get("SR") if info.get("SR") is not None else (
                        round(10 ** _si, 6) if _si is not None else None
                    )
                    all_si[mineral] = {
                        "SI":               _si,
                        "SR":               _sr,
                        "log_IAP":          info.get("log_IAP"),
                        "log_K":            info.get("log_K"),
                        "chemical_formula": info.get("chemical_formula"),
                    }
                else:
                    _si = float(info)
                    all_si[mineral] = {
                        "SI": _si,
                        "SR": round(10 ** _si, 6),
                    }

            # Merge indices (from _enrich_grid_points) and calculations
            # (from _add_calculations_to_results) — calculations takes priority.
            # This ensures all 5 indices are ALWAYS present regardless of salt.
            _idx  = r.get("indices", {}) or {}
            _calc = r.get("calculations", {}) or {}
            _merged = {**_idx, **_calc}

            _NA_CA_ALK = {"interpretation": "N/A", "risk": "N/A", "note": "Requires Calcium and Alkalinity in water sample"}
            _NA_IONS   = {"interpretation": "N/A", "risk": "N/A", "note": "Requires Cl, SO4, and Alkalinity in water sample"}
            merged_indices = {
                "lsi":          _merged.get("lsi")          or {"lsi":      None, **_NA_CA_ALK},
                "ryznar":       _merged.get("ryznar")       or {"ri":       None, **_NA_CA_ALK},
                "puckorius":    _merged.get("puckorius")    or {"index":    None, **_NA_CA_ALK},
                "ccpp":         _merged.get("ccpp")         or {"ccpp_ppm": None, **_NA_CA_ALK},
                "stiff_davis":  _merged.get("stiff_davis")  or {"index":    None, **_NA_CA_ALK},
                "larson_skold": _merged.get("larson_skold") or {"index":    None, **_NA_IONS},
            }

            sr_val = round(10 ** si_val, 4) if si_val is not None else None
            r["bar_data"] = {
                "color_hex": _COLOUR_HEX.get(r["color_code"], "#BDC3C7"),
                "opacity": opacity,
                "sr_color": "green" if (sr_val is not None and sr_val < 1) else "red",
                "sr_color_hex": _COLOUR_HEX.get("green") if (sr_val is not None and sr_val < 1) else _COLOUR_HEX.get("red"),
            }

            points.append({
                "coc":         r["_grid_CoC"],
                "temperature": temp_display,
                "ph":          r["_grid_pH"],
                "si":          si_val,
                "color":       r["color_code"],
                "color_hex":   _COLOUR_HEX.get(r["color_code"], "#BDC3C7"),
                "opacity":     opacity,
                "ionic_strength":            r.get("ionic_strength"),
                "charge_balance_error_pct":  r.get("charge_balance_error_pct"),
                "activity_of_water":         desc.get("activity_of_water"),
                "all_si": all_si,
                "indices":       merged_indices,
                "water_balance": r.get("water_balance", {}),
                "chemical":      r.get("chemical", {}),
                # ── Corrosion: merge _enrich_grid_points data with _add_calculations fallback ──
                "corrosion":     _build_corrosion_for_point(r),
                # ── Description of Solution: PHREEQC values + root-level fallbacks ──
                "description_of_solution": {
                    "ph":                   desc.get("pH") or r.get("_grid_pH"),
                    "temperature_c":        desc.get("temperature_C") or r.get("_grid_temp_c"),
                    "specific_conductance": desc.get("specific_conductance") or r.get("specific_conductance"),
                    "density":              desc.get("density") or r.get("density"),
                    "activity_of_water":    desc.get("activity_of_water"),
                    "ionic_strength":       desc.get("ionic_strength_desc") or r.get("ionic_strength"),
                    "dissolved_oxygen_ppm": r.get("dissolved_oxygen_ppm"),
                    "charge_balance_error_pct": r.get("charge_balance_error_pct"),
                    "electrical_balance":   r.get("electrical_balance"),
                    "mass_of_water_kg":     desc.get("mass_of_water_kg"),
                },
                "distribution_of_species": r.get("distribution_of_species", {}),
                "electrical_balance":      r.get("electrical_balance", 0.0),
            })

        unique_coc  = sorted(set(p["coc"]         for p in points))
        unique_temp = sorted(set(p["temperature"] for p in points))

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
            # available_salts: only user-requested salts that PHREEQC calculated
            # If no specific salts were requested, fall back to all minerals
            "available_salts": (
                sorted(set(
                    matched
                    for req_s in (requested_salts or [])
                    for p in points[:1]           # check first point only
                    for mineral in (p.get("all_si") or {}).keys()
                    for matched in ([mineral] if mineral.lower() == req_s.lower() else [])
                ))
                if requested_salts
                else sorted(set(
                    mineral
                    for p in points
                    for mineral in (p.get("all_si") or {}).keys()
                ))
            ),
            "points":       points,
        }

    # ── STEP: build table_data (separate from chart_data, for frontend tables) ─
    @staticmethod
    def _build_table_data(
        results: List[Dict[str, Any]],
        salt_id: Optional[str],
        temp_unit: str,
    ) -> Dict[str, Any]:
        """
        Build a flat, table-ready data structure from grid results.
        Parallel to chart_data — lives at the top level of the response.
        Frontend can use this directly to render tables without parsing chart_data.points.
        """
        temp_suffix = "°F" if temp_unit.upper() == "F" else "°C"

        grid_overview: List[Dict] = []
        saturation_indices: List[Dict] = []
        deposition_indices: List[Dict] = []
        water_balance: List[Dict] = []
        chemical_dosage: List[Dict] = []
        corrosion_rates: List[Dict] = []
        description_of_solution: List[Dict] = []
        distribution_of_species: List[Dict] = []

        for r in results:
            coc  = r.get("_grid_CoC")
            temp = round(r.get("_grid_temp", 0), 2)
            ph   = r.get("_grid_pH")
            desc = r.get("description_of_solution") or {}

            # ── 1. Grid Overview ──────────────────────────────────────────────
            si_info = r.get("saturation_indices", {}).get(salt_id) if salt_id else None
            if si_info is not None:
                si_val = si_info.get("SI") if isinstance(si_info, dict) else float(si_info)
                sr_val = si_info.get("SR") if (isinstance(si_info, dict) and si_info.get("SR") is not None) else (
                    round(10 ** si_val, 6) if si_val is not None else None
                )
            else:
                si_val = sr_val = None

            grid_overview.append({
                "coc":                      coc,
                "ph":                       ph,
                "si":                       si_val,
                "sr":                       sr_val,
                "color":                    r.get("color_code"),
                "color_hex":                _COLOUR_HEX.get(r.get("color_code", ""), "#BDC3C7"),
                "ionic_strength":           r.get("ionic_strength"),
                "charge_balance_error_pct": r.get("charge_balance_error_pct"),
            })

            # ── 2. All Saturation Indices ─────────────────────────────────────
            _si_rows = []
            for mineral, info in (r.get("saturation_indices") or {}).items():
                if isinstance(info, dict):
                    _s  = info.get("SI")
                    _sr = info.get("SR") if info.get("SR") is not None else (
                        round(10 ** _s, 6) if _s is not None else None
                    )
                    _si_rows.append({
                        "mineral":          mineral,
                        "si":               _s,
                        "sr":               _sr,
                        "log_iap":          info.get("log_IAP"),
                        "log_k":            info.get("log_K"),
                        "chemical_formula": info.get("chemical_formula"),
                    })
                else:
                    _s = float(info)
                    _si_rows.append({
                        "mineral": mineral,
                        "si":      _s,
                        "sr":      round(10 ** _s, 6),
                    })
            saturation_indices.append({
                "coc":         coc,
                "temperature": temp,
                "temp_unit":   temp_suffix,
                "minerals":    _si_rows,
            })

            # ── 3. Deposition Indices ─────────────────────────────────────────
            idx = r.get("indices") or {}
            calcs = r.get("calculations") or {}
            merged = {**idx, **calcs}

            def _index_row(key, full_name, val_key):
                data = merged.get(key) or {}
                return {
                    "index_key":    key,
                    "index_name":   key.upper().replace("_", "-"),
                    "full_name":    full_name,
                    "value":        data.get(val_key),
                    "interpretation": data.get("interpretation"),
                    "risk":         data.get("risk") or data.get("risk_level"),
                }

            deposition_indices.append({
                "coc":         coc,
                "temperature": temp,
                "temp_unit":   temp_suffix,
                "indices": [
                    _index_row("lsi",          "Langelier Saturation Index",               "lsi"),
                    _index_row("ryznar",        "Ryznar Stability Index",                   "ri"),
                    _index_row("puckorius",     "Puckorius Scaling Index",                  "index"),
                    _index_row("ccpp",          "Calcium Carbonate Precipitation Potential","ccpp_ppm"),
                    _index_row("stiff_davis",   "Stiff & Davis Stability Index",            "index"),
                    _index_row("larson_skold",  "Larson-Skold Index",                       "index"),
                ],
            })

            # ── 4. Water Balance (per grid point) ─────────────────────────────
            wb = r.get("water_balance") or {}
            water_balance.append({
                "coc":              coc,
                "temperature":      temp,
                "temp_unit":        temp_suffix,
                "evaporation_gpm":  (wb.get("evaporation") or {}).get("evaporation_rate_gpm"),
                "blowdown_gpm":     (wb.get("blowdown") or {}).get("blowdown_rate_gpm"),
                "makeup_gpm":       (wb.get("makeup") or {}).get("makeup_rate_gpm"),
                "drift_gpm":        (wb.get("makeup") or {}).get("drift_rate_gpm"),
            })

            # ── 5. Chemical Dosage (per grid point) ───────────────────────────
            chem = r.get("chemical") or {}
            lbs_day  = chem.get("lbs_per_day")
            lbs_year = chem.get("lbs_per_year")
            chemical_dosage.append({
                "coc":               coc,
                "temperature":       temp,
                "temp_unit":         temp_suffix,
                "product":           chem.get("product"),
                "dosage_ppm":        chem.get("dosage_ppm"),
                "lbs_per_day":       lbs_day,
                "kg_per_day":        round(lbs_day * 0.453592, 4) if lbs_day else None,
                "lbs_per_year":      lbs_year,
                "kg_per_year":       round(lbs_year * 0.453592, 2) if lbs_year else None,
                "cost_per_day_usd":  chem.get("cost_per_day_usd"),
                "cost_per_year_usd": chem.get("cost_per_year_usd"),
            })

            # ── 6. Corrosion Rates ────────────────────────────────────────────
            # Merge r["corrosion"] (from _enrich_grid_points) with
            # r["calculations"] fallback (from _add_calculations_to_results).
            # Covers: mild_steel, copper, admiralty_brass
            corr = dict(r.get("corrosion") or {})
            _calc_corr = r.get("calculations") or {}

            _metal_calc_map = {
                "mild_steel":      "mild_steel_corrosion",
                "copper":          "copper_corrosion",
                "admiralty_brass": "admiralty_brass_corrosion",
            }
            for _mk, _ck in _metal_calc_map.items():
                if _mk not in corr and _ck in _calc_corr:
                    ms = _calc_corr[_ck]
                    corr[_mk] = {
                        "cr_mpy":                   ms.get("cr_mpy"),
                        "cr_base_mpy":              ms.get("cr_base_mpy"),
                        "total_inhibition_percent": ms.get("total_inhibition_percent"),
                        "rating":                   ms.get("rating"),
                        "risk_level":               ms.get("rating"),
                        "do_ppm_used":              ms.get("do_ppm_used") or (ms.get("components") or {}).get("do_ppm"),
                        "components":               ms.get("components"),
                        "note":                     ms.get("note"),
                        "source":                   "calculations",
                    }

            _corr_rows = []
            metal_labels = {
                "mild_steel":      "Mild Steel",
                "copper":          "Copper",
                "admiralty_brass": "Admiralty Brass",
            }
            for metal_key, metal_label in metal_labels.items():
                if metal_key in corr:
                    m = corr[metal_key]
                    _corr_rows.append({
                        "metal":                    metal_label,
                        "metal_key":                metal_key,
                        "cr_mpy":                   m.get("cr_mpy"),
                        "cr_base_mpy":              m.get("cr_base_mpy"),
                        "total_inhibition_percent": m.get("total_inhibition_percent"),
                        "rating":                   m.get("rating"),
                        "risk_level":               m.get("risk_level") or m.get("rating") or m.get("risk"),
                        "do_ppm_used":              m.get("do_ppm_used"),
                        "components":               m.get("components"),
                        "note":                     m.get("note"),
                        "source":                   m.get("source"),
                    })
            corrosion_rates.append({
                "coc":         coc,
                "temperature": temp,
                "temp_unit":   temp_suffix,
                "metals":      _corr_rows,
            })

            # ── 7. Description of Solution ────────────────────────────────────
            # desc = r["description_of_solution"] (from PHREEQC parser)
            # Fallback to root-level grid point fields when desc is empty/missing
            description_of_solution.append({
                "coc":                  coc,
                "temperature_c":        desc.get("temperature_C") or r.get("_grid_temp_c"),
                "ph":                   desc.get("pH") or ph,
                "specific_conductance": desc.get("specific_conductance") or r.get("specific_conductance"),
                "density":              desc.get("density") or r.get("density"),
                "activity_of_water":    desc.get("activity_of_water"),
                "ionic_strength":       desc.get("ionic_strength_desc") or r.get("ionic_strength"),
                "dissolved_oxygen_ppm": r.get("dissolved_oxygen_ppm"),
                "charge_balance_error_pct": r.get("charge_balance_error_pct"),
                "electrical_balance":   r.get("electrical_balance"),
                "mass_of_water_kg":     desc.get("mass_of_water_kg"),
            })

            # ── 8. Distribution of Species ────────────────────────────────────
            _species_rows = []
            for species, sp_data in (r.get("distribution_of_species") or {}).items():
                if isinstance(sp_data, dict):
                    _species_rows.append({
                        "species":  species,
                        "molality": sp_data.get("molality"),
                        "activity": sp_data.get("activity"),
                        "element":  sp_data.get("element"),
                    })
            distribution_of_species.append({
                "coc":         coc,
                "temperature": temp,
                "temp_unit":   temp_suffix,
                "species":     _species_rows,
            })

        return {
            "grid_overview":            grid_overview,
            "saturation_indices":       saturation_indices,
            "deposition_indices":       deposition_indices,
            "water_balance":            water_balance,
            "chemical_dosage":          chemical_dosage,
            "corrosion_rates":          corrosion_rates,
            "description_of_solution":  description_of_solution,
            "distribution_of_species":  distribution_of_species,
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
        mapped_water: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """
        For each grid point, calculate LSI, RSI, PSI, CCPP, mild steel corrosion.
        Uses mapped_water (normalized ion keys) for accurate calculations.
        """
        try:
            from app.services.calculation_service import CalculationService
            calc = CalculationService()
        except Exception as e:
            logger.warning(f"CalculationService unavailable: {e}")
            return results

        for r in results:
            try:
                coc = float(r.get("_grid_CoC", 1.0))

                # Build params with BOTH raw keys AND normalized keys,
                # with ALL ion concentrations multiplied by CoC.
                params: Dict[str, Any] = {}

                # 1. Start with raw_water (original OCR keys) × CoC
                for k, v in raw_water.items():
                    if isinstance(v, dict):
                        raw_val = float(v.get("value", 0) or 0)
                        unit    = v.get("unit", "mg/L") or "mg/L"
                        key_l   = k.lower().replace(" ", "_")
                        # Don't multiply pH, Temperature, Conductivity by CoC
                        if key_l in ("ph", "temperature", "temp", "conductivity",
                                     "electrical_conductivity"):
                            params[k] = v
                        else:
                            params[k] = {"value": round(raw_val * coc, 4), "unit": unit}
                    else:
                        params[k] = v

                # 2. Add normalized mapped keys × CoC
                if mapped_water:
                    for k, v in mapped_water.items():
                        if k.startswith("_"):
                            params[k] = v  # internal metadata keys — don't multiply
                            continue
                        if k in ("pH", "Temperature", "pe"):
                            params[k] = v
                        elif isinstance(v, dict):
                            raw_val = float(v.get("value", 0) or 0)
                            params[k] = {**v, "value": round(raw_val * coc, 4)}
                        else:
                            try:
                                params[k] = round(float(v) * coc, 4)
                            except (TypeError, ValueError):
                                params[k] = v

                    # Also add common aliases that calculation_service expects
                    alias_map = {
                        "Ca":   ["Calcium", "calcium"],
                        "Mg":   ["Magnesium", "magnesium"],
                        "Na":   ["Sodium", "sodium"],
                        "K":    ["Potassium", "potassium"],
                        "Cl":   ["Chloride", "chloride"],
                        "SO4":  ["Sulfate", "Sulphate", "sulfate", "sulphate"],
                        "HCO3": ["Alkalinity", "Bicarbonate", "alkalinity", "bicarbonate"],
                        "SiO2": ["Silica", "Silicon", "silica"],
                        "Fe":   ["Iron", "iron"],
                        "PO4":  ["Phosphate", "phosphate"],
                    }
                    for ion_key, aliases in alias_map.items():
                        if ion_key in params:
                            for alias in aliases:
                                if alias not in params:
                                    params[alias] = params[ion_key]

                # 3. Estimate TDS from Conductivity if not provided
                # TDS ≈ 0.67 × Conductivity (standard approximation) × CoC
                tds = 0.0
                for tds_key in ("TDS", "Total_Dissolved_Solids", "tds"):
                    if tds_key in params:
                        v = params[tds_key]
                        tds = float(v.get("value", 0) if isinstance(v, dict) else v)
                        break
                if tds == 0.0:
                    for cond_key in ("Conductivity", "conductivity",
                                     "Electrical_Conductivity", "electrical_conductivity"):
                        cond_raw = raw_water.get(cond_key)
                        if cond_raw is not None:
                            cond_val = float(
                                cond_raw.get("value", 0) if isinstance(cond_raw, dict)
                                else cond_raw
                            )
                            if cond_val > 0:
                                tds = round(0.67 * cond_val * coc, 2)
                                break
                if tds > 0:
                    params["TDS"] = {"value": tds, "unit": "mg/L"}

                # Use natural pH from CO2 equilibration (correct pH)
                grid_ph   = float(r.get("_grid_pH") or r.get("_natural_ph_at_cold") or 7.0)
                # Use _grid_temp_c (Celsius) for calculations — _grid_temp is user's unit
                grid_temp = float(r.get("_grid_temp_c") or r.get("_grid_temp") or 25.0)

                params["pH"]          = {"value": grid_ph,   "unit": ""}
                params["Temperature"] = {"value": grid_temp,  "unit": "°C"}

                ionic_strength = float(r.get("ionic_strength") or 0.0)

                phreeqc_output = {
                    "ionic_strength":     ionic_strength,
                    "saturation_indices": [
                        {"mineral_name": k, "si_value": v.get("SI", 0.0)}
                        for k, v in r.get("saturation_indices", {}).items()
                    ],
                }

                calcs: Dict[str, Any] = {}

                for method_name in ("lsi", "ryznar", "puckorius", "larson_skold"):
                    try:
                        method = getattr(calc, f"calculate_{method_name}")
                        calcs[method_name] = await method(params)
                    except Exception:
                        pass

                # CCPP — needs PHREEQC equilibrium_phases or Calcite SI
                try:
                    # Try direct PHREEQC equilibrium_phases first
                    ccpp_phreeqc = {
                        "equilibrium_phases": r.get("equilibrium_phases", {}),
                        "saturation_indices": phreeqc_output["saturation_indices"],
                    }
                    ccpp_result = await calc.calculate_ccpp(ccpp_phreeqc)
                    # If calcite_moles was 0, estimate from Calcite SI instead
                    if ccpp_result.get("ccpp_ppm") == 0 and ccpp_result.get("calcite_moles") == 0:
                        calcite_si_val = next(
                            (item["si_value"] for item in phreeqc_output["saturation_indices"]
                             if item["mineral_name"].lower() == "calcite"), None
                        )
                        ca_conc = float(params.get("Ca", {}).get("value", 0) if isinstance(params.get("Ca"), dict) else params.get("Ca", 0))
                        if calcite_si_val is not None and ca_conc > 0:
                            ca_caco3 = ca_conc * (100.09 / 40.08)
                            est_ccpp = round(calcite_si_val * ca_caco3 / 10, 2)
                            ccpp_result = {
                                "ccpp_ppm": est_ccpp,
                                "interpretation": "Heavy Scale Forming" if est_ccpp > 15 else ("Slight Scale Forming" if est_ccpp > 0 else ("Slight Dissolution" if est_ccpp >= -15 else "Corrosive")),
                                "risk": "High Scale Risk" if est_ccpp > 15 else ("Moderate Scale Risk" if est_ccpp > 0 else ("Low Corrosion" if est_ccpp >= -15 else "Corrosive")),
                                "source": "Estimated from Calcite SI",
                            }
                    calcs["ccpp"] = ccpp_result
                except Exception:
                    pass

                # Stiff & Davis — always pass ionic_strength
                try:
                    calcs["stiff_davis"] = await calc.calculate_stiff_davis(params, ionic_strength)
                except Exception:
                    pass

                try:
                    sat_indices_dict = {
                        item["mineral_name"]: item["si_value"]
                        for item in phreeqc_output["saturation_indices"]
                    }
                    # Temperature-based DO estimate (Henry's law for open cooling water)
                    # Same formula used by _enrich_grid_points — no hardcoded do_ppm
                    _tc = r.get("_grid_temp_c", r["_grid_temp"])
                    do_ppm_calc = max(0.0, round(
                        14.62 - 0.3898 * _tc + 0.006969 * _tc**2 - 0.00005896 * _tc**3, 2
                    ))
                    _ph = float(r.get("_grid_pH") or grid_ph)

                    # ── Mild Steel ────────────────────────────────────────────
                    try:
                        ms_result = await calc.calculate_mild_steel_corrosion(
                            params, sat_indices_dict, do_ppm=do_ppm_calc, temp_c=_tc
                        )
                        calcs["mild_steel_corrosion"] = {**ms_result, "do_ppm_used": do_ppm_calc}
                    except Exception:
                        pass

                    # ── Copper ────────────────────────────────────────────────
                    try:
                        cu_result = await calc.calculate_copper_corrosion(
                            params, sat_indices_dict, do_ppm=do_ppm_calc, temp_c=_tc, pH=_ph
                        )
                        calcs["copper_corrosion"] = {**cu_result, "do_ppm_used": do_ppm_calc}
                    except Exception:
                        pass

                    # ── Admiralty Brass (Copper × 0.85 factor) ────────────────
                    try:
                        ab_result = await calc.calculate_copper_corrosion(
                            params, sat_indices_dict, do_ppm=do_ppm_calc, temp_c=_tc, pH=_ph
                        )
                        calcs["admiralty_brass_corrosion"] = {
                            **ab_result,
                            "cr_mpy":      round(ab_result["cr_mpy"] * 0.85, 2),
                            "cr_base_mpy": round(ab_result["cr_base_mpy"] * 0.85, 2),
                            "do_ppm_used": do_ppm_calc,
                            "note":        "Admiralty Brass rate = Copper × 0.85",
                        }
                    except Exception:
                        pass

                except Exception:
                    pass

                r["calculations"] = calcs

                # ── Build standalone corrosion_rate object on grid point ────────
                # Clean, minimal object — only essential display fields.
                # grid_results[i].corrosion_rate.mild_steel / .copper / .admiralty_brass
                _existing_corr = r.get("corrosion") or {}

                def _pick(enrich_key: str, calc_key: str) -> Optional[Dict]:
                    """Return clean corrosion data for one metal — essential fields only."""
                    src = _existing_corr.get(enrich_key) or calcs.get(calc_key)
                    if not src:
                        return None
                    out = {
                        "cr_mpy":      src.get("cr_mpy"),
                        "cr_base_mpy": src.get("cr_base_mpy"),
                        "rating":      src.get("rating"),
                    }
                    # Only include note if it has a value (Admiralty Brass label)
                    if src.get("note"):
                        out["note"] = src["note"]
                    return out

                r["corrosion_rate"] = {
                    "do_ppm":          do_ppm_calc,
                    "temp_c":          _tc,
                    "mild_steel":      _pick("mild_steel",      "mild_steel_corrosion"),
                    "copper":          _pick("copper",          "copper_corrosion"),
                    "admiralty_brass": _pick("admiralty_brass", "admiralty_brass_corrosion"),
                }

            except Exception as e:
                logger.warning(f"Calculations failed for CoC={r.get('_grid_CoC')}: {e}")
                r["calculations"] = {}

        return results

    # ─────────────────────────────────────────────────────────────────────────
    # COOLING TOWER ANALYSIS
    # ─────────────────────────────────────────────────────────────────────────
    async def _calculate_cooling_tower_analysis(
        self,
        asset_info: Dict[str, Any],
        coc_list: List[float],
        dosage_ppm: float,
        product_blend: Optional[Dict[str, Any]],
        mapped_params: Optional[Dict[str, Any]] = None,
        grid_results: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        Full dynamic cooling tower analysis from asset_info payload.
        All values safely extracted with fallback defaults.
        System-level metrics calculated once; per-CoC metrics per CoC value.
        """
        def _safe_float(val: Any, default: float = 0.0) -> float:
            return _robust_safe_float(val, default)

        def _to_f(val: Any, unit: str) -> Optional[float]:
            """Convert any temperature to °F."""
            if val is None:
                return None
            v = _safe_float(val)
            u = (unit or "").strip().upper().replace(" ", "")
            if u in ("°C", "C", "CELSIUS", "DEGC"):
                return round(v * 9 / 5 + 32, 2)
            return round(v, 2)  # already °F

        # ── Extract asset_info fields ──────────────────────────────────────────
        recirc_raw       = asset_info.get("recirculationRate")
        recirc_unit      = (asset_info.get("recirculationRateType") or "gpm").upper()
        recirc_gpm       = _safe_float(recirc_raw, 0.0)
        if "M3" in recirc_unit or "M³" in recirc_unit:
            recirc_gpm = round(recirc_gpm * 4.40287, 2)  # m³/hr → gpm

        supply_temp_raw  = asset_info.get("supplyTemperature")
        supply_temp_unit = asset_info.get("supplyTemperatureType") or "°F"
        cold_temp_f      = _to_f(supply_temp_raw, supply_temp_unit)

        return_temp_raw  = asset_info.get("returnTemperature")
        return_temp_unit = asset_info.get("returnTemperatureType") or "°F"
        hot_temp_f       = _to_f(return_temp_raw, return_temp_unit)

        # Ensure hot > cold (swap if inverted due to unit mismatch)
        if hot_temp_f is not None and cold_temp_f is not None and hot_temp_f < cold_temp_f:
            hot_temp_f, cold_temp_f = cold_temp_f, hot_temp_f

        delta_raw        = asset_info.get("deltaTemperature")
        delta_f          = abs(_safe_float(delta_raw)) if delta_raw is not None else None

        wb_raw           = asset_info.get("wetBulbTempF") or asset_info.get("wetBulbTemp")
        wb_unit          = asset_info.get("wetBulbTempUnit") or "°F"
        wet_bulb_f       = _to_f(wb_raw, wb_unit) if wb_raw is not None else None

        drift_pct        = _safe_float(asset_info.get("driftPercent"), 0.1)
        evap_factor_pct  = _safe_float(asset_info.get("evaporationFactorPercent"), 85.0)
        cooling_tons_in  = _safe_float(asset_info.get("tonnageOfCooling"), 0.0)
        approach_to_wb   = _safe_float(asset_info.get("approachToWB"), 0.0)
        skin_temp_raw    = asset_info.get("hottestSkinTemperature")
        skin_temp_unit   = asset_info.get("hottestSkinTemperatureType") or "°F"
        skin_temp_f      = _to_f(skin_temp_raw, skin_temp_unit) if skin_temp_raw is not None else None

        pb               = product_blend or {}
        cost_per_lb      = _safe_float(pb.get("costPerLb"), 0.0)
        product_name     = pb.get("productName") or "Product"
        operating_days   = int(_safe_float(pb.get("operatingDaysPerYear"), 350))

        # ── System-level: Range ────────────────────────────────────────────────
        if hot_temp_f is not None and cold_temp_f is not None:
            range_f = round(hot_temp_f - cold_temp_f, 2)
        elif delta_f is not None:
            range_f = delta_f
        else:
            range_f = None

        # ── System-level: Approach ────────────────────────────────────────────
        approach_source = None
        if cold_temp_f is not None and wet_bulb_f is not None:
            approach_f = round(cold_temp_f - wet_bulb_f, 2)
            approach_source = "Calculated (Cold Water Temp - Wet Bulb Temp)"
        elif approach_to_wb > 0:
            approach_f = approach_to_wb
            approach_source = "approachToWB field"
            if cold_temp_f is None and wet_bulb_f is not None:
                cold_temp_f = round(wet_bulb_f + approach_f, 2)
            elif wet_bulb_f is None and cold_temp_f is not None:
                wet_bulb_f = round(cold_temp_f - approach_f, 2)
        elif wet_bulb_f is not None:
            approach_f = 7.0
            approach_source = "Default fallback (Supply Temp not provided)"
            if cold_temp_f is None:
                cold_temp_f = round(wet_bulb_f + approach_f, 2)
        elif cold_temp_f is not None:
            approach_f = 7.0
            approach_source = "Default fallback (Wet Bulb Temp not provided)"
            wet_bulb_f = round(cold_temp_f - approach_f, 2)
        else:
            approach_f = None

        # If cold_temp_f was missing but we have wet_bulb and approach, estimate it
        if cold_temp_f is None and wet_bulb_f is not None and approach_f is not None:
            cold_temp_f = round(wet_bulb_f + approach_f, 2)

        # If hot_temp_f was missing but we have cold_temp and range, estimate it
        if hot_temp_f is None and cold_temp_f is not None and range_f is not None:
            hot_temp_f = round(cold_temp_f + range_f, 2)

        # ── System-level: Dissolved Oxygen ────────────────────────────────────
        ref_temp_f = hot_temp_f if hot_temp_f is not None else cold_temp_f
        if ref_temp_f is not None:
            tw_c  = round((ref_temp_f - 32) * 5 / 9, 2)
            if wet_bulb_f is not None:
                twb_c = round((wet_bulb_f - 32) * 5 / 9, 2)
            elif skin_temp_f is not None:
                twb_c = round((skin_temp_f - 32) * 5 / 9, 2)
            else:
                twb_c = max(tw_c - 5.0, 5.0)
            do_ppm_sys = round(max(0.0, 14.6 - 0.41 * tw_c - 0.05 * (tw_c - twb_c)), 2)
        else:
            tw_c = twb_c = None
            do_ppm_sys = 5.0

        # ── Build system dict ──────────────────────────────────────────────────
        system: Dict[str, Any] = {
            "recirculation_rate_gpm": recirc_gpm if recirc_gpm > 0 else None,
            "hot_water_temp_f":       hot_temp_f,
            "cold_water_temp_f":      cold_temp_f,
            "wet_bulb_temp_f":        wet_bulb_f,
            "skin_temp_f":            skin_temp_f,
            "drift_percent":          drift_pct,
            "drift_gpm":              round(recirc_gpm * drift_pct / 100.0, 2) if recirc_gpm > 0 else None,
            "evaporation_factor_pct": evap_factor_pct,
            "cooling_tons_input":     cooling_tons_in if cooling_tons_in > 0 else None,
            "range": {
                "range_f": range_f,
            },
            "approach": {
                "approach_f": approach_f,
                # Temperature difference conversion: ΔF × 5/9 = ΔC (no -32 offset)
                "approach_c": round(approach_f * 5 / 9, 2) if approach_f is not None else None,
                **({"source": approach_source} if approach_source is not None else {}),
                **({"note": "Wet bulb temperature not provided"} if approach_f is None else {}),
            },
            "efficiency": (
                {"efficiency_percent": round((range_f / (range_f + approach_f)) * 100, 2)}
                if range_f is not None and approach_f is not None and (range_f + approach_f) > 0
                else {"efficiency_percent": None, "note": "Range or Approach not available"}
            ),
            "heat_load": (
                {"heat_load_btu_hr": round(500 * recirc_gpm * range_f, 0),
                 "heat_load_tons":   round(500 * recirc_gpm * range_f / 12000, 2)}
                if recirc_gpm > 0 and range_f is not None
                else {"heat_load_btu_hr": None, "note": "Recirculation rate or range not available"}
            ),
            "cooling_tons": (
                {"calculated_tons": round((recirc_gpm * range_f) / 30, 2),
                 "input_tons":      cooling_tons_in if cooling_tons_in > 0 else None}
                if recirc_gpm > 0 and range_f is not None and range_f > 0
                else {"calculated_tons": None,
                      "input_tons": cooling_tons_in if cooling_tons_in > 0 else None}
            ),
            "dissolved_oxygen": {
                "do_ppm":          do_ppm_sys,
                "water_temp_c":    tw_c,
                "wet_bulb_temp_c": twb_c,
                "note":            "Per-CoC DO values are in grid_results[].dissolved_oxygen_ppm (calculated from PHREEQC O2 molality). This is a system-level estimate only.",
                **({"estimation": "wet bulb estimated (5°C below water temp)"} if wet_bulb_f is None and skin_temp_f is None and ref_temp_f is not None else {}),
                **({"estimation": "Default fallback (temperatures not provided)"} if ref_temp_f is None else {}),
            },
        }

        # ── Per-CoC calculations ───────────────────────────────────────────────
        per_coc: List[Dict[str, Any]] = []
        for coc in coc_list:
            entry: Dict[str, Any] = {"coc": coc}

            # Evaporation Rate
            if recirc_gpm > 0 and range_f is not None:
                evap_gpm = round(0.01 * recirc_gpm * (range_f / 10.0) * (evap_factor_pct / 100.0), 3)
                entry["evaporation"] = {
                    "evaporation_rate_gpm": evap_gpm,
                    "evaporation_factor_pct": evap_factor_pct,
                }
            else:
                evap_gpm = None
                entry["evaporation"] = {"evaporation_rate_gpm": None, "note": "Recirculation rate or range not available"}

            # Blowdown Rate
            if evap_gpm is not None and coc > 1:
                bd_gpm = round(evap_gpm / (coc - 1), 3)
                entry["blowdown"] = {"blowdown_rate_gpm": bd_gpm}
            elif coc <= 1:
                bd_gpm = None
                entry["blowdown"] = {"blowdown_rate_gpm": None, "note": "CoC must be > 1"}
            else:
                bd_gpm = None
                entry["blowdown"] = {"blowdown_rate_gpm": None, "note": "Evaporation rate not available"}

            # Makeup Rate
            if evap_gpm is not None and bd_gpm is not None:
                drift_gpm  = round(recirc_gpm * (drift_pct / 100.0), 4)
                makeup_gpm = round(evap_gpm + bd_gpm + drift_gpm, 3)
                entry["makeup"] = {
                    "makeup_rate_gpm":      makeup_gpm,
                    "evaporation_rate_gpm": evap_gpm,
                    "blowdown_rate_gpm":    bd_gpm,
                    "drift_rate_gpm":       drift_gpm,
                    "drift_percent":        drift_pct,
                }
            else:
                entry["makeup"] = {"makeup_rate_gpm": None, "note": "Evaporation or blowdown not available"}

            # Chemical Dosage
            chem: Dict[str, Any] = {"product": product_name, "dosage_ppm": dosage_ppm}
            if bd_gpm is not None and bd_gpm > 0:
                million_lbs_bd = round((bd_gpm * 60 * 24 * 8.34) / 1_000_000, 6)
                chem_lbs_day   = round(dosage_ppm * million_lbs_bd, 4)
                chem_lbs_year  = round(chem_lbs_day * operating_days, 2)
                chem.update({
                    "million_lbs_blowdown_per_day": million_lbs_bd,
                    "lbs_per_day":                  chem_lbs_day,
                    "lbs_per_year":                 chem_lbs_year,
                    "operating_days_per_year":      operating_days,
                })
                if cost_per_lb > 0:
                    chem.update({
                        "cost_per_million_lbs_bd": round(dosage_ppm * cost_per_lb, 2),
                        "cost_per_day_usd":        round(chem_lbs_day * cost_per_lb, 4),
                        "cost_per_year_usd":       round(chem_lbs_year * cost_per_lb, 2),
                    })
            else:
                chem.update({"lbs_per_day": None, "lbs_per_year": None,
                             "note": "Blowdown not available (CoC ≤ 1 or data missing)"})
            entry["chemical"] = chem

            # Add cycled water parameters if mapped params available
            try:
                if mapped_params:
                    # Use hot_temp_f as evaluation temp when present, else cold_temp_f
                    temp_display = hot_temp_f if hot_temp_f is not None else (cold_temp_f if cold_temp_f is not None else 25.0)
                    temp_c = round((float(temp_display) - 32) * 5 / 9, 2)

                    # Use PHREEQC-calculated pH for this CoC from grid_results.
                    # The grid may have multiple temps per CoC — use the first match
                    # (all share the same natural pH from Step 1 CO2 equilibration).
                    calculated_ph = None
                    if grid_results:
                        for gr in grid_results:
                            if gr.get("_grid_CoC") == coc:
                                calculated_ph = gr.get("_grid_pH")
                                break
                    if calculated_ph is None:
                        # Fallback: use raw makeup water pH
                        calculated_ph = _get_ion_value(mapped_params, "pH") or float(
                            mapped_params.get("pH", 7.0)
                            if not isinstance(mapped_params.get("pH"), dict)
                            else mapped_params.get("pH").get("value", 7.0)
                        )
                    natural_ph = calculated_ph

                    desc = {}  # no PHREEQC description available in this context
                    do_ppm = do_ppm_sys
                    entry["cycled_water_parameters"] = _build_cycled_water_params(
                        mapped_params, coc, temp_display, temp_c, natural_ph, desc, do_ppm
                    )
                else:
                    entry["cycled_water_parameters"] = None
            except Exception:
                entry["cycled_water_parameters"] = None

            per_coc.append(entry)

        return {"system": system, "per_coc": per_coc}
    def _evaluate_formula(self, formula_str: str, sr_val: float) -> Optional[float]:
        """
        Evaluate inhibition formula at a given SR value.
        Returns dose_required = f(SR), or None if parse fails.

        Handles:
          1. Power:     Dose = A × SR^B
          2. Quadratic: Dose = A×SR^2 + B×SR + C
          3. Linear:    Dose = A×SR + B
        """
        if not formula_str or sr_val is None:
            return None
        try:
            import re
            import math

            f = formula_str.lower().strip()
            f = re.sub(r'^(y|dose|d)\s*=\s*', '', f)
            f = re.sub(r'\bsr\s*\([^)]*\)', 'sr', f)
            f = f.replace('\u00d7', '*').replace('\u00b2', '^2').replace('\u00b3', '^3')
            # Handle implicit multiply: digit immediately followed by 'x' or 'x(' → insert '*'
            f = re.sub(r'(\d)x\s*\(', r'\1 * (', f)   # e.g. 1.0947x((  → 1.0947 * ((
            f = re.sub(r'(\d)x(?=[\d\s])', r'\1 *', f) # e.g. 1.0947x 5 → 1.0947 * 5
            f = re.sub(r'(?<=[\d\w\)]) x (?=[\d\w\(sr])', ' * ', f)
            f = re.sub(r'\bx\b', 'sr', f)
            f = re.sub(r'\bsi\b', 'sr', f)
            f = f.replace('(', ' ').replace(')', ' ')
            f = re.sub(r'\bsr\s*\*\s*([\d.]+)', r'\1 * sr', f)
            f = re.sub(r'\s+', ' ', f).strip()

            # ── 1. Power: A * sr^B (non-integer exponent) ────────────────────
            mp = re.search(r'([\d.]+)\s*\*?\s*sr\s*\^?\s*([\d.]+)', f)
            if mp:
                a = float(mp.group(1))
                b = float(mp.group(2))
                if b not in (1.0, 2.0) and a > 0 and b > 0:
                    dose = a * (sr_val ** b)
                    return round(dose, 6)

            # ── 2. Quadratic: A * sr^2 + B * sr + C ──────────────────────────
            mq = re.search(
                r'([\d.]+)\s*\*?\s*sr\s*\^?\s*2\s*([+\-])\s*([\d.]+)\s*\*?\s*sr\s*([+\-])\s*([\d.]+)',
                f
            )
            if mq:
                a = float(mq.group(1))
                b = float(mq.group(3)) * (1 if mq.group(2) == '+' else -1)
                c = float(mq.group(5)) * (1 if mq.group(4) == '+' else -1)
                dose = a * (sr_val ** 2) + b * sr_val + c
                return round(dose, 6)

            # ── 3. Linear: A * sr + B ─────────────────────────────────────────
            ml = re.search(r'([\d.]+)\s*\*?\s*sr(?:\s*([+\-])\s*([\d.]+))?', f)
            if ml:
                a = float(ml.group(1))
                b = 0.0
                if ml.group(3):
                    b = float(ml.group(3)) * (1 if ml.group(2) == '+' else -1)
                dose = a * sr_val + b
                return round(dose, 6)

        except Exception as e:
            logger.warning(f"_evaluate_formula failed for '{formula_str}' at SR={sr_val}: {e}")
        return None

    def _solve_for_sr(self, formula_str: str, dosage_ppm: float) -> Optional[float]:
        """
        Solve inhibition formula for SR given a dosage value.

        Handles formula formats:
          1. Power:     Dose = A × SR^B          → SR = (Dose/A)^(1/B)
          2. Quadratic: Dose = A×SR^2 + B×SR + C → quadratic formula
          3. Linear:    Dose = A×SR + B           → SR = (Dose - B) / A

        Returns the positive SR value, or None if parse fails.
        """
        if not formula_str:
            return None
        try:
            import re
            import math

            f = formula_str.lower().strip()

            # ── Normalize left-hand side ─────────────────────────────────────
            f = re.sub(r'^(y|dose|d)\s*=\s*', '', f)

            # ── Normalize SR variable: "SR(Calcite)", "SR(Hydroxyapatite)" → "sr" ──
            f = re.sub(r'\bsr\s*\([^)]*\)', 'sr', f)

            # ── Normalize operators (unicode × ² ³) ─────────────────────────
            f = f.replace('\u00d7', '*').replace('\u00b2', '^2').replace('\u00b3', '^3')

            # ── 'x' as multiply operator between terms → '*' ─────────────────
            f = re.sub(r'(?<=[\d\w\)]) x (?=[\d\w\(sr])', ' * ', f)

            # standalone 'x' (variable) and 'si' → 'sr'
            f = re.sub(r'\bx\b', 'sr', f)
            f = re.sub(r'\bsi\b', 'sr', f)

            # ── Remove surrounding parentheses ───────────────────────────────
            f = f.replace('(', ' ').replace(')', ' ')

            # ── Reorder "sr * coeff" → "coeff * sr" ─────────────────────────
            f = re.sub(r'\bsr\s*\*\s*([\d.]+)', r'\1 * sr', f)

            f = re.sub(r'\s+', ' ', f).strip()

            # ── 1. Try power: A * sr^B (non-integer exponent) ────────────────
            # Pattern: "1.0947 * sr ^ 0.1038"
            mp = re.search(
                r'([\d.]+)\s*\*?\s*sr\s*\^?\s*([\d.]+)',
                f
            )
            if mp:
                a = float(mp.group(1))
                b = float(mp.group(2))
                # Only treat as power formula if exponent is NOT 1 or 2
                # (to avoid false match with linear/quadratic)
                if b not in (1.0, 2.0) and a > 0 and b > 0:
                    # Dose = A × SR^B  →  SR = (Dose / A)^(1/B)
                    sr_val = (dosage_ppm / a) ** (1.0 / b)
                    if sr_val > 0:
                        logger.info(
                            f"Power formula: A={a}, B={b} → SR={sr_val:.4f} at dose={dosage_ppm}"
                        )
                        return round(sr_val, 6)

            # ── 2. Try quadratic: A * sr^2 + B * sr + C ─────────────────────
            mq = re.search(
                r'([\d.]+)\s*\*?\s*sr\s*\^?\s*2\s*([+\-])\s*([\d.]+)\s*\*?\s*sr\s*([+\-])\s*([\d.]+)',
                f
            )
            if mq:
                a = float(mq.group(1))
                b = float(mq.group(3)) * (1 if mq.group(2) == '+' else -1)
                c = float(mq.group(5)) * (1 if mq.group(4) == '+' else -1)

                # Equation: a*sr^2 + b*sr + (c - dosage_ppm) = 0
                discriminant = b**2 - 4 * a * (c - dosage_ppm)
                if discriminant >= 0:
                    sr1 = (-b + math.sqrt(discriminant)) / (2 * a)
                    sr2 = (-b - math.sqrt(discriminant)) / (2 * a)
                    positive_roots = [r for r in [sr1, sr2] if r > 0]
                    if positive_roots:
                        return max(positive_roots)
                logger.warning(f"Negative discriminant in SR formula: {formula_str}")
                return None

            # ── 3. Try linear: A * sr + B ────────────────────────────────────
            ml = re.search(r'([\d.]+)\s*\*?\s*sr(?:\s*([+\-])\s*([\d.]+))?', f)
            if ml:
                a = float(ml.group(1))
                b = 0.0
                if ml.group(3):
                    b = float(ml.group(3)) * (1 if ml.group(2) == '+' else -1)
                if a != 0:
                    return (dosage_ppm - b) / a

            logger.warning(f"Could not match any formula pattern in: '{formula_str}' (normalized: '{f}')")

        except Exception as e:
            logger.warning(f"Could not parse SR inhibition formula '{formula_str}': {e}")
        return None

    def _parse_applicable_ionic_strength(self, app_is_str: Optional[str]) -> Tuple[float, float]:
        """
        Parse applicable ionic strength from string format.
        
        Supports formats:
        - "<0.1"       → (0.0, 0.1)
        - "0.1-0.5"    → (0.1, 0.5)
        - ">1.0"       → (1.0, 999.0)
        - None/empty   → (0.0, 999.0) [covers all ranges]
        
        Returns: (min_is, max_is) tuple
        """
        if not app_is_str or isinstance(app_is_str, (int, float)):
            return 0.0, 999.0
        
        app_is_str = str(app_is_str).strip()
        
        try:
            # Handle "<value" format
            if "<" in app_is_str:
                val = float(app_is_str.replace("<", "").replace(">", "").strip())
                return 0.0, val
            
            # Handle ">value" format
            if ">" in app_is_str:
                val = float(app_is_str.replace("<", "").replace(">", "").strip())
                return val, 999.0
            
            # Handle "min-max" format
            if "-" in app_is_str:
                parts = app_is_str.split("-")
                if len(parts) == 2:
                    return float(parts[0].strip()), float(parts[1].strip())
            
            # Single numeric value — treat as exact match with 0.01 tolerance
            val = float(app_is_str)
            return val, val + 0.01
        
        except (ValueError, TypeError) as e:
            logger.warning(f"Could not parse applicableIonicStrength '{app_is_str}': {e}, defaulting to all ranges")
            return 0.0, 999.0

    async def _enrich_product_blend_from_db(self, req: Dict[str, Any]) -> Dict[str, Any]:
        """
        When product_blend.rawMaterials contains items with only rawId (no formula data),
        fetch the full raw material documents from the DB and inject them as rawMaterialData.

        Also handles the case where product_blend.productId is set but rawMaterials is empty —
        fetches the full product from DB to get the rawMaterials list.

        DB schema:
          raw_materials collection:
            { commonName, activePercentage, bandUpperCushion, bandLowerCushion,
              formulas: [{ salToInhibit, applicableIonicStrength, formulaForInhibitionPerformance }] }

          products collection:
            { rawMaterials: [{ rawId, percentage, nameSnapshot }] }
        """
        product_data = req.get("product_blend")
        if not product_data:
            return req

        # ── Step 1: If product_blend has a productId but no rawMaterials, fetch product from DB ──
        product_id = product_data.get("productId")
        raw_materials_list = product_data.get("rawMaterials")

        if product_id and not raw_materials_list:
            try:
                from bson import ObjectId
                prod_doc = await db.db["products"].find_one(
                    {"_id": ObjectId(product_id)},
                    {"_id": 0, "rawMaterials": 1, "waterPercentage": 1}
                )
                if prod_doc and prod_doc.get("rawMaterials"):
                    raw_materials_list = prod_doc["rawMaterials"]
                    product_data = dict(product_data)
                    product_data["rawMaterials"] = raw_materials_list
                    req = dict(req)
                    req["product_blend"] = product_data
                    logger.info(f"Fetched {len(raw_materials_list)} rawMaterials from productId={product_id}")
            except Exception as e:
                logger.warning(f"Could not fetch product from DB (productId={product_id}): {e}")

        # ── Step 2: For each rawMaterial item without rawMaterialData, fetch from DB ──
        if not isinstance(raw_materials_list, list) or not raw_materials_list:
            return req

        enriched_items = []
        for rm_item in raw_materials_list:
            # Already has rawMaterialData or rawMaterialChemistry — nothing to do
            if rm_item.get("rawMaterialData") or rm_item.get("rawMaterialChemistry"):
                enriched_items.append(rm_item)
                continue

            # ── FIX: If the payload already carries inhibitionFormulas directly on the
            # rm_item (as happens with PRODUCT blend payloads), do NOT fetch from DB.
            # Fetching from DB could overwrite the payload formulas with stale/empty
            # DB data, causing 'undefined' errors in the analysis pipeline.
            # Instead, wrap the rm_item itself as rawMaterialData so downstream code
            # (process_raw_material) can find inhibitionFormulas, activePercentage, etc.
            if rm_item.get("inhibitionFormulas"):
                enriched_item = dict(rm_item)
                # Build rawMaterialData from the payload fields already on rm_item
                rm_data_from_payload = {
                    "commonName":            rm_item.get("nameSnapshot") or rm_item.get("activeComponentName", ""),
                    "activeComponentName":   rm_item.get("activeComponentName", ""),
                    "activePercentage":      rm_item.get("activePercentage"),
                    "activePercentageChemicalFormula": rm_item.get("activePercentageChemicalFormula", ""),
                    "inhibitionFormulas":    rm_item.get("inhibitionFormulas", []),
                    # Cushions default to 5%/10% — these are rarely in the payload
                    "bandUpperCushion":      rm_item.get("bandUpperCushion", "5%"),
                    "bandLowerCushion":      rm_item.get("bandLowerCushion", "10%"),
                }
                enriched_item["rawMaterialData"] = rm_data_from_payload
                enriched_items.append(enriched_item)
                logger.info(
                    f"rawMaterial '{rm_item.get('nameSnapshot')}' has inhibitionFormulas "
                    f"directly in payload — skipping DB fetch, using payload data directly. "
                    f"Formulas count: {len(rm_item.get('inhibitionFormulas', []))}"
                )
                continue

            raw_id = rm_item.get("rawId") or rm_item.get("rawMaterialId")
            if not raw_id:
                enriched_items.append(rm_item)
                continue

            try:
                from bson import ObjectId
                rm_doc = await db.db["raw_materials"].find_one(
                    {"_id": ObjectId(raw_id)},
                    {"_id": 0}
                )
                if rm_doc:
                    # Normalise: DB uses 'formulas' key, code expects 'inhibitionFormulas'
                    if "formulas" in rm_doc and "inhibitionFormulas" not in rm_doc:
                        rm_doc["inhibitionFormulas"] = rm_doc["formulas"]

                    # ── FIX: If the payload rm_item has inhibitionFormulas, always prefer
                    # them over the DB version — payload is the authoritative source.
                    payload_formulas = rm_item.get("inhibitionFormulas")
                    if payload_formulas:
                        rm_doc["inhibitionFormulas"] = payload_formulas
                        logger.info(
                            f"rawMaterial rawId={raw_id}: payload inhibitionFormulas "
                            f"({len(payload_formulas)}) preferred over DB formulas."
                        )

                    # Merge payload-level activePercentage into rm_doc if missing in DB
                    if rm_item.get("activePercentage") and not rm_doc.get("activePercentage"):
                        rm_doc["activePercentage"] = rm_item["activePercentage"]

                    enriched_item = dict(rm_item)
                    enriched_item["rawMaterialData"] = rm_doc
                    enriched_items.append(enriched_item)
                    logger.info(
                        f"Enriched rawMaterial rawId={raw_id} "
                        f"({rm_doc.get('commonName')}) with "
                        f"{len(rm_doc.get('inhibitionFormulas') or [])} formulas"
                    )
                else:
                    logger.warning(f"Raw material not found in DB: rawId={raw_id}")
                    # ── FIX: Even when DB lookup fails, preserve the rm_item as-is
                    # so any inhibitionFormulas on the payload item are not lost.
                    enriched_items.append(rm_item)
            except Exception as e:
                logger.warning(f"Could not fetch rawMaterial rawId={raw_id}: {e}")
                enriched_items.append(rm_item)

        # Update req with enriched rawMaterials
        product_data = dict(product_data)
        product_data["rawMaterials"] = enriched_items
        req = dict(req)
        req["product_blend"] = product_data
        return req

    def _apply_dynamic_colors(

        self,
        results: List[Dict[str, Any]],
        req: Dict[str, Any],
        salt_id: Optional[str]
    ) -> List[Dict[str, Any]]:
        """
        Dynamically applies colors to the entire dataset based on dataset min/max ionic strength,
        product vs raw material inputs, and calculating BreakpointSR.
        """
        if not results:
            return results

        # 1. Determine min and max Ionic Strength for the entire dataset
        ionic_strengths = [r.get("ionic_strength", 0.0) for r in results]
        min_is = min(ionic_strengths) if ionic_strengths else 0.0
        max_is = max(ionic_strengths) if ionic_strengths else 0.0

        raw_material_data = req.get("raw_material_chemistry")
        product_data = req.get("product_blend") or req.get("product")
        user_dosage_ppm = _robust_safe_float(req.get("dosage_ppm"), 2.0)
        
        logger.info(
            f"_apply_dynamic_colors: user_dosage={user_dosage_ppm}, "
            f"dataset_is=[{min_is:.4f}, {max_is:.4f}], "
            f"has_raw_material_data={bool(raw_material_data)}, "
            f"has_product_data={bool(product_data)}"
        )

        # 2. Extract active formulas per salt based on input
        # Dictionary of salt_name -> (formula_str, dosage_ppm, band_lower_pct, band_upper_pct)
        # We store the formula + dosage and evaluate forward (calc dose from actual SR)
        # rather than solving inverse (which breaks for power formulas like A*SR^B)
        salt_formulas: Dict[str, Tuple[str, float, float, float]] = {}

        def process_raw_material(rm_data, dosage):
            if not rm_data:
                return
            
            # Helper to parse cushion values
            def _to_float(v, default=5.0):
                try:
                    if isinstance(v, str):
                        v = v.replace("%", "").strip()
                    return float(v)
                except (TypeError, ValueError):
                    return default
            
            band_lower_pct = _to_float(rm_data.get("bandLowerCushion"), 5.0)
            band_upper_pct = _to_float(rm_data.get("bandUpperCushion"), 5.0)

            # DB stores formulas under 'formulas' key; payload may use 'inhibitionFormulas'
            formulas = rm_data.get("inhibitionFormulas") or rm_data.get("formulas") or []
            for formula_obj in formulas:
                salt_to_inhibit = formula_obj.get("salToInhibit", "")
                if not salt_to_inhibit:
                    continue
                
                # Parse Applicable Ionic Strength range
                app_is_str = formula_obj.get("applicableIonicStrength", "")
                app_is_min, app_is_max = self._parse_applicable_ionic_strength(app_is_str)
                
                # Check overlap
                if min_is == 0 and max_is == 0:
                    overlaps = True
                else:
                    overlaps = (min_is <= app_is_max) and (max_is >= app_is_min)
                    if not overlaps:
                        logger.debug(
                            f"IS range [{min_is:.4f}, {max_is:.4f}] does not overlap "
                            f"[{app_is_min:.4f}, {app_is_max:.4f}] for {salt_to_inhibit}"
                        )

                if not overlaps:
                    continue

                formula_str = formula_obj.get("formulaForInhibitionPerformance", "")
                if not formula_str:
                    continue
                
                salt_lower = salt_to_inhibit.lower()
                # Store formula + dosage (keep first match per salt)
                if salt_lower not in salt_formulas:
                    salt_formulas[salt_lower] = (formula_str, dosage, band_lower_pct, band_upper_pct)
                    logger.info(
                        f"Stored formula for {salt_to_inhibit} at dose={dosage:.2f}ppm "
                        f"(IS: {app_is_str}): {formula_str[:60]}..."
                    )

        # 3. Handle Product vs Raw Material Input
        # Supports multiple payload structures:
        #   A) product_blend.rawMaterials[] — blended product with multiple raw materials
        #   B) product_blend.rawMaterialChemistry — single raw material embedded in product
        #   C) product_blend itself has inhibitionFormulas — treat as raw material directly
        #   D) raw_material_chemistry — single raw material (fallback)
        if product_data:
            if isinstance(product_data.get("rawMaterials"), list) and product_data["rawMaterials"]:
                # Case A: blended product
                for rm_item in product_data["rawMaterials"]:
                    # Robust fallback to rm_item itself if nested rawMaterialData is missing
                    rm_chem = rm_item.get("rawMaterialData") or rm_item.get("rawMaterialChemistry") or rm_item
                    if not rm_chem:
                        continue
                    # DB uses 'percentage', payload may use 'percentageInProduct'
                    pct_in_prod = _robust_safe_float(
                        rm_item.get("percentageInProduct")
                        or rm_item.get("percentage")
                        or 100.0,
                        100.0
                    ) / 100.0
                    active_pct = _robust_safe_float(rm_chem.get("activePercentage"), 100.0) / 100.0
                    rm_dosage = user_dosage_ppm * pct_in_prod * active_pct
                    process_raw_material(rm_chem, rm_dosage)
            elif product_data.get("rawMaterialChemistry"):
                # Case B: single raw material embedded
                rm_chem = product_data["rawMaterialChemistry"]
                active_pct = _robust_safe_float(rm_chem.get("activePercentage"), 100.0) / 100.0
                process_raw_material(rm_chem, user_dosage_ppm * active_pct)
            elif product_data.get("inhibitionFormulas"):
                # Case C: product_blend itself has inhibitionFormulas
                process_raw_material(product_data, user_dosage_ppm)
            elif raw_material_data:
                # Fallback to raw_material_chemistry
                process_raw_material(raw_material_data, user_dosage_ppm)
        elif raw_material_data:
            # Case D: only raw_material_chemistry provided
            # dosage_ppm here is the direct active ingredient dose —
            # do NOT apply activePercentage (that applies only when dosing a product blend)
            process_raw_material(raw_material_data, user_dosage_ppm)

        # 4. Apply colors using FORWARD calculation:
        #    Calculate dose_required = f(SR_actual) and compare with user dosage.
        #    Green  → dose_required ≤ dosage × (1 + band_upper%)   [treatment sufficient]
        #    Yellow → dosage × (1 + band_upper%) < dose_required ≤ dosage × (1 + 2×band_upper%)
        #    Red    → dose_required > dosage × (1 + 2×band_upper%) [treatment insufficient]
        logger.info(f"Applying colors with {len(salt_formulas)} active salt formulas: {list(salt_formulas.keys())}")

        for r in results:
            si_detail = r.get("saturation_indices", {})
            per_salt_colors = {}

            for mineral_name, mineral_data in si_detail.items():
                si_val_raw = mineral_data.get("SI", 0.0)
                sr_val = mineral_data.get("SR")
                if sr_val is None:
                    sr_val = round(10 ** si_val_raw, 6)

                # Determine the formula evaluation variable.
                # Client formulas use "SR(MineralName)" notation, but the actual
                # value expected by the formula is the Saturation Ratio = 10^SI.
                # However, for minerals with very high SI (e.g. Hydroxyapatite SI > 5),
                # using raw SR (10^8+) produces unrealistically large dose values.
                # Industry-standard inhibition performance formulas are calibrated
                # against SR values typically in the range 1–1000 (SI 0–3).
                # When SR > 10000 (SI > 4), we pass SI directly as the formula variable
                # so the formula behaves as Dose = f(SI) which is the practical range.
                formula_input = sr_val

                matched_formula = None
                mineral_lower = mineral_name.lower()

                for s_to_inh, formula_data in salt_formulas.items():
                    if s_to_inh in mineral_lower or mineral_lower in s_to_inh:
                        matched_formula = formula_data
                        break

                if matched_formula:
                    formula_str, dosage, b_lower, b_upper = matched_formula

                    # Forward: calculate dose required at this SR (or SI for extreme values)
                    dose_required = self._evaluate_formula(formula_str, formula_input)

                    if dose_required is None:
                        # Formula evaluation failed — fallback to SR < 1 logic
                        c = "green" if sr_val < 1 else "red"
                    else:
                        # Client color band logic:
                        #   b_lower (e.g. 10%) = lower cushion → green threshold
                        #   b_upper (e.g. 5%)  = upper cushion → yellow threshold
                        #
                        # The "lower cushion" means: if dose_required is within
                        # (dosage - b_lower%) of the user dosage → Green (treatment working)
                        # The "upper cushion" means: beyond (dosage + b_upper%) → Red
                        #
                        # Correct interpretation:
                        #   green_thresh  = dosage * (1 - b_lower / 100)  ← dose must be ≤ this
                        #   yellow_thresh = dosage * (1 + b_upper / 100)  ← above this → red
                        #
                        # If dose_required ≤ green_thresh  → Green  (treatment is sufficient)
                        # If dose_required ≤ yellow_thresh → Yellow (caution zone)
                        # Else                             → Red    (treatment insufficient)
                        green_thresh  = dosage * (1 - b_lower / 100.0)
                        yellow_thresh = dosage * (1 + b_upper / 100.0)

                        if dose_required <= green_thresh:
                            c = "green"
                        elif dose_required <= yellow_thresh:
                            c = "yellow"
                        else:
                            c = "red"

                        logger.info(
                            f"COLOR_CALC {mineral_name}: SR={sr_val:.4f} "
                            f"formula_input={formula_input:.4f} "
                            f"dose_req={dose_required:.4f} user_dose={dosage:.2f} "
                            f"green_thresh={green_thresh:.4f} yellow_thresh={yellow_thresh:.4f} "
                            f"→ {c.upper()}"
                        )
                else:
                    # No formula — default: SR < 1 = green, else red
                    c = "green" if sr_val < 1 else "red"

                per_salt_colors[mineral_name] = c

            r["per_salt_colors"] = per_salt_colors
            
            # Set primary color_code (Case-insensitive match for salt_id)
            target_salt = (salt_id or "").lower()
            assigned_color = "green"
            for m_name, m_color in per_salt_colors.items():
                if m_name.lower() == target_salt:
                    assigned_color = m_color
                    break
            else:
                # Fallback to the first available salt's color if salt_id not found
                if per_salt_colors:
                    assigned_color = next(iter(per_salt_colors.values()))
            
            r["color_code"] = assigned_color

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

        # FIX 3: Convert CaCO3-reported values to elemental mg/L
        mapped = _convert_caco3_units(mapped, raw_water)
        logger.info(
            f"Water params after CaCO3 conversion: "
            f"Ca={_get_ion_value(mapped,'Ca')}, "
            f"Mg={_get_ion_value(mapped,'Mg')}, "
            f"HCO3={_get_ion_value(mapped,'HCO3')}, "
            f"pH={_get_ion_value(mapped,'pH')}"
        )

        # ── 2. pH adjustment chemical — FIX 1: no ion modification ───────────
        # _apply_ph_adjustment now returns params unchanged.
        # balance_anion is auto-resolved from the chemical name below.
        mapped = _apply_ph_adjustment(mapped, req.get("adjustment_chemical"))

        # ── 3. ph_mode: fixed pH override (optional) ──────────────────────────
        ph_mode  = req.get("ph_mode", "natural")
        fixed_ph = req.get("fixed_ph")
        co2_factor_override = req.get("co2_log_partial_pressure")

        if ph_mode == "fixed" and fixed_ph is not None:
            mapped["pH"] = {"value": float(fixed_ph), "unit": ""}
            # When pH is fixed externally, skip CO2 equilibration
            co2_factor_override = None   # will trigger None return below
            logger.info(f"Fixed pH mode: pH={fixed_ph}, CO2 equilibration will be skipped")

        # ── 4. Thresholds from raw_material_chemistry ─────────────────────────
        # Note: Thresholds and color coding are now calculated dynamically AFTER
        # the entire PHREEQC pipeline finishes so we can determine the dataset's
        # min and max ionic strength.
        thresholds = {}
        dosage_ppm = _robust_safe_float(req.get("dosage_ppm"), 2.0)

        # ── 5. Resolve temperatures ───────────────────────────────────────────
        asset_info = req.get("asset_info") or {}

        # --- AI Wet Bulb Estimation ---
        if asset_info.get("wetBulbTempF") is None and asset_info.get("wetBulbTemp") is None:
            location = req.get("customer_information", {}).get("location") or asset_info.get("location") or asset_info.get("city")
            if location:
                try:
                    from app.services.weather_ai_service import WeatherAIService
                    weather_ai = WeatherAIService()
                    estimated_wb = await weather_ai.estimate_wet_bulb_temp(
                        location=location,
                        date_str=req.get("date")
                    )
                    if estimated_wb is not None:
                        asset_info["wetBulbTempF"] = estimated_wb
                        logger.info(f"Injected AI-estimated wet bulb temp {estimated_wb}°F into asset_info")
                except Exception as e:
                    logger.error(f"Error during AI wet bulb estimation: {e}")
        # ------------------------------

        cold_temp_raw  = asset_info.get("supplyTemperature") or req.get("temp_min") or 32.2
        cold_temp_unit = asset_info.get("supplyTemperatureType") or req.get("temp_unit") or "°F"
        cold_temp_c    = _to_celsius(_robust_safe_float(cold_temp_raw, 32.2), cold_temp_unit)

        hot_temp_raw   = asset_info.get("returnTemperature") or req.get("temp_max") or 55.0
        hot_temp_unit  = asset_info.get("returnTemperatureType") or req.get("temp_unit") or "°F"
        hot_temp_c     = _to_celsius(_robust_safe_float(hot_temp_raw, 55.0), hot_temp_unit)

        if hot_temp_c < cold_temp_c:
            logger.warning(
                f"Hot temp ({hot_temp_c}°C) < cold temp ({cold_temp_c}°C) — "
                f"likely unit mismatch. Swapping."
            )
            cold_temp_c, hot_temp_c = hot_temp_c, cold_temp_c

        logger.info(f"Temperatures: cold={cold_temp_c}°C, hot={hot_temp_c}°C")

        # ── 6. CO2 factor ─────────────────────────────────────────────────────
        approach_to_wb = asset_info.get("approachToWB") or 7.0

        co2_factor = _calculate_co2_factor(
            system_type    = asset_info.get("type") or asset_info.get("systemType"),
            tower_type     = asset_info.get("towerType"),
            fill_type      = asset_info.get("fillType"),
            draft_type     = asset_info.get("draftType"),
            approach_to_wb = _robust_safe_float(approach_to_wb, 7.0),
            co2_override   = co2_factor_override,
        )

        # If fixed pH mode was requested, disable CO2 equilibration
        if ph_mode == "fixed" and fixed_ph is not None:
            co2_factor = None
            logger.info("Fixed pH mode active — CO2 equilibration disabled")

        logger.info(f"CO2 factor: {co2_factor}")

        # ── 7. Charge balance ion resolution — FIX 1 extension ───────────────
        balance_cation, balance_anion = _resolve_balance_ion_from_chemical(
            chemical               = req.get("adjustment_chemical"),
            explicit_balance_anion = req.get("balance_anion"),
            explicit_balance_cation= req.get("balance_cation"),
        )
        logger.info(f"Charge balance: cation={balance_cation}, anion={balance_anion}")

        # ── 8. Build CoC list ─────────────────────────────────────────────────
        coc_min      = _robust_safe_float(req.get("coc_min"), 1.0)
        coc_max      = _robust_safe_float(req.get("coc_max"), 10.0)
        coc_interval = _robust_safe_float(req.get("coc_interval"), 1.0)
        coc_list     = self._build_coc_list(coc_min, coc_max, coc_interval)
        logger.info(f"CoC list: {coc_list}")

        # ── 9. Build evaluation temperature list ──────────────────────────────
        temp_unit     = req.get("temp_unit", "F")
        temp_min_raw  = _robust_safe_float(req.get("temp_min"), 110.0)
        temp_max_raw  = _robust_safe_float(req.get("temp_max"), 160.0)
        temp_interval = _robust_safe_float(req.get("temp_interval"), 10.0)

        temp_list_c:   List[float] = []  # Celsius — for PHREEQC internal use
        temp_list_raw: List[float] = []  # Original user input — for _grid_temp display
        t = temp_min_raw
        while t <= temp_max_raw + 1e-9:
            temp_list_c.append(_to_celsius(t, temp_unit))
            temp_list_raw.append(round(t, 2))  # keep exact user input value
            t += max(temp_interval, 0.1)

        if not temp_list_c:
            temp_list_c   = [hot_temp_c]
            temp_list_raw = [round(_robust_safe_float(req.get("temp_min"), 110.0), 2)]

        logger.info(f"Eval temp list (°C): {temp_list_c}")
        logger.info(f"Eval temp list (raw user unit): {temp_list_raw}")
        logger.info(f"Grid: {len(coc_list)} CoC × {len(temp_list_c)} Temp = {len(coc_list)*len(temp_list_c)} points")

        # ── 10. Run 2-step PHREEQC pipeline ──────────────────────────────────
        salt_id           = req.get("salt_id")
        salts_of_interest = req.get("salts_of_interest")

        logger.info("Balancing water parameters upfront before grid simulation...")
        mapped = await self.phreeqc.ion_balance(
            water_params=mapped,
            cation_ion=balance_cation,
            anion_ion=balance_anion
        )

        results, db_used = await self._run_two_step_pipeline(
            mapped_params     = {
                **mapped,
                # Pass wet bulb temp for per-CoC DO calculation
                "_wet_bulb_temp_c": (
                    round((_robust_safe_float(asset_info.get("wetBulbTempF")) - 32) * 5 / 9, 2)
                    if asset_info.get("wetBulbTempF") is not None
                    else None
                ),
            },
            coc_list          = coc_list,
            cold_temp_c       = cold_temp_c,
            temp_list_c       = temp_list_c,
            temp_list_raw     = temp_list_raw,
            co2_factor        = co2_factor,
            balance_cation    = balance_cation,
            balance_anion     = balance_anion,
        )

        # ── 10.5 Enrich product_blend with raw material chemistry from DB ────
        # When product_blend.rawMaterials contains only rawId (no formula data),
        # fetch the full raw material documents from DB and inject them.
        req = await self._enrich_product_blend_from_db(req)

        # ── 10.6 Apply Dynamic Colors based on Dataset IS and SR thresholds ──
        results = self._apply_dynamic_colors(results, req, salt_id)

        # ── 11. Add additional calculations per grid point ────────────────────
        results = await self._add_calculations_to_results(results, raw_water, mapped)

        # ── 11b. Cooling Tower Analysis ────────────────────────────────────────
        try:
            cooling_tower_analysis = await self._calculate_cooling_tower_analysis(
                asset_info   = asset_info,
                coc_list     = coc_list,
                dosage_ppm   = _robust_safe_float(req.get("dosage_ppm"), 2.0),
                product_blend= req.get("product_blend"),
                mapped_params= mapped,
                grid_results = results,
            )
        except Exception as e:
            logger.warning(f"Cooling tower analysis failed (non-fatal): {e}")
            cooling_tower_analysis = {"error": str(e)}

        # ── 12. Resolve effective salt (case-insensitive) ─────────────────────
        effective_salt = salt_id
        phreeqc_available_salts: List[str] = []   # ALL minerals PHREEQC calculated (internal)
        if results:
            sample_si = results[0].get("saturation_indices", {})
            phreeqc_available_salts = sorted(sample_si.keys())
            logger.info(f"PHREEQC returned {len(phreeqc_available_salts)} minerals: {phreeqc_available_salts[:15]}")

            if salt_id:
                found = any(k.lower() == salt_id.lower() for k in phreeqc_available_salts)
                if not found:
                    logger.warning(f"salt_id '{salt_id}' not found. Available: {phreeqc_available_salts[:10]}. Using first.")
                    effective_salt = phreeqc_available_salts[0] if phreeqc_available_salts else None
                else:
                    effective_salt = next(k for k in phreeqc_available_salts if k.lower() == salt_id.lower())
            else:
                effective_salt = phreeqc_available_salts[0] if phreeqc_available_salts else None

        # Build list of user-requested salts
        all_requested = list(set(
            ([salt_id] if salt_id else []) +
            (salts_of_interest or [])
        ))

        # available_salts = only the user-selected salts that PHREEQC actually calculated
        # (NOT all minerals — only the ones the user asked for)
        phreeqc_lower = {k.lower(): k for k in phreeqc_available_salts}
        available_salts: List[str] = []
        for req_salt in all_requested:
            matched = phreeqc_lower.get(req_salt.lower())
            if matched:
                available_salts.append(matched)
        available_salts = sorted(set(available_salts))
        logger.info(f"User-requested salts found in PHREEQC output: {available_salts}")

        # unavailable_salts = user-requested salts that PHREEQC did NOT calculate (with reasons)
        unavailable_salts = _get_unavailable_salts_with_reasons(
            all_requested, phreeqc_available_salts, mapped
        )

        # ── 13. Generate graph ────────────────────────────────────────────────
        graph_url = "not-generated"
        try:
            png       = self._generate_graph(results, effective_salt, run_id, temp_unit)
            graph_url = self._upload_s3(png, run_id)
        except Exception as e:
            logger.warning(f"Graph generation/upload failed (non-fatal): {e}")

        # ── 14. Build Plotly-ready graph_data ─────────────────────────────────
        graph_data = self._build_graph_data(results, effective_salt, temp_unit)

        # ── 14b. Build table_data (flat, table-ready — parallel to chart_data) ─
        table_data = self._build_table_data(results, effective_salt, temp_unit)

        # ── 15. Summary ───────────────────────────────────────────────────────
        summary = self._summary(results)

        # ── 16. Save to DB ────────────────────────────────────────────────────
        # Build balance override warnings for frontend display
        raw_cation_input = req.get("balance_cation", "Na") or "Na"
        raw_anion_input  = req.get("balance_anion",  "Cl") or "Cl"
        balance_warnings: List[str] = []

        # Normalize input for comparison (strip charge symbols like 2+, -, etc.)
        def _strip_charge(s: str) -> str:
            return s.upper().replace("2+","").replace("+","").replace("2-","").replace("-","").strip()

        if _strip_charge(raw_cation_input) not in ("NA", "K"):
            balance_warnings.append(
                f"balance_cation '{raw_cation_input}' is not valid for PHREEQC "
                f"(Ca²⁺ and Mg²⁺ cannot be used as charge balance ions). "
                f"Using 'Na' instead."
            )
        if _strip_charge(raw_anion_input) not in ("CL", "SO4", "S6"):
            balance_warnings.append(
                f"balance_anion '{raw_anion_input}' is not valid for PHREEQC "
                f"(HCO₃⁻ creates circular dependency in carbonate system). "
                f"Using 'Cl' instead."
            )

        # Extract customer info from request
        customer_info = req.get("customer_info") or {}
        
        # Extract per_coc from cooling_tower_analysis for top-level exposure (duplicate reference)
        per_coc_top = None
        if isinstance(cooling_tower_analysis, dict):
            per_coc_top = cooling_tower_analysis.get("per_coc")

        doc = {
            "run_id":                  run_id,
            "salt_id":                 effective_salt,
            "salts_of_interest":       salts_of_interest,
            "dosage_ppm":              _robust_safe_float(req.get("dosage_ppm"), 2.0),
            "coc_min":                 coc_min,
            "coc_max":                 coc_max,
            "coc_interval":            coc_interval,
            "cold_basin_temp_c":       cold_temp_c,
            "hot_basin_temp_c":        hot_temp_c,
            "temp_unit":               temp_unit,
            "ph_mode":                 ph_mode,
            "fixed_ph":                fixed_ph,
            "co2_factor":              co2_factor,
            "adjustment_chemical":     req.get("adjustment_chemical"),
            # What user requested vs what was actually used
            "balance_cation_requested": raw_cation_input,
            "balance_anion_requested":  raw_anion_input,
            "balance_cation":          balance_cation,   # actually used in PHREEQC
            "balance_anion":           balance_anion,    # actually used in PHREEQC
            "balance_warnings":        balance_warnings, # non-empty if override happened
            "database_used":           db_used,
            "total_grid_points":       len(results),
            "available_salts":         available_salts,    # only user-requested salts found in PHREEQC output
            "unavailable_salts":       unavailable_salts,  # user-requested salts PHREEQC could not calculate + reason
            "grid_results":            results,
            "graph_url":               graph_url,
            "graph_data":              graph_data,
            "summary":                 summary,
            "thresholds":              thresholds,
            "base_water_parameters":   raw_water,
            "product_blend":           req.get("product_blend"),
            "raw_material_chemistry":  req.get("raw_material_chemistry"),
            "asset_info":              asset_info,
            "customer_info":           customer_info,
            "cooling_tower_analysis":  cooling_tower_analysis,
            "Per_Cycle_Conection":     per_coc_top,
            # ── Convenience object: all 3 sections in one place for frontend ──
            "asset_summary": {
                # 1. Customer Information
                "customer_information": {
                    "name":     customer_info.get("name"),
                    "site_name": customer_info.get("siteName"),
                    "location":  customer_info.get("location"),
                    "address":   customer_info.get("address"),
                } if customer_info else None,
                # 2. Asset Information
                "asset_information": {
                    "name":             asset_info.get("name"),
                    "type":             asset_info.get("type"),
                    "tower_type":       asset_info.get("towerType"),
                    "system_volume":    asset_info.get("systemVolume"),
                    "recirculation_rate_gpm": asset_info.get("recirculationRate"),
                    "supply_temperature":     asset_info.get("supplyTemperature"),
                    "supply_temperature_unit":asset_info.get("supplyTemperatureType", "°F"),
                    "return_temperature":     asset_info.get("returnTemperature"),
                    "return_temperature_unit":asset_info.get("returnTemperatureType", "°F"),
                    "wet_bulb_temperature":   asset_info.get("wetBulbTempF"),
                    "hottest_skin_temperature": asset_info.get("hottestSkinTemperature"),
                    "fill_type":        asset_info.get("fillType"),
                    "draft_type":       asset_info.get("draftType"),
                },
                # 3. Materials
                "materials": {
                    "metallurgy": asset_info.get("systemMetallurgy") or [],
                    "system_materials": asset_info.get("systemMaterials") or [],
                },
                # 4. Cooling Tower Analysis (system-level only, DO removed — see grid_results[].dissolved_oxygen_ppm)
                "cooling_tower_analysis": {
                    **{
                        k: v for k, v in (
                            cooling_tower_analysis.get("system") or {}
                        ).items()
                        if k != "dissolved_oxygen"   # DO is per-CoC → in grid_results[].dissolved_oxygen_ppm
                    },
                    # Ensure all 4 temperature fields are exposed
                    "supply_temperature_f":   asset_info.get("supplyTemperature"),
                    "return_temperature_f":   asset_info.get("returnTemperature"),
                    "wet_bulb_temp_f":        (cooling_tower_analysis.get("system") or {}).get("wet_bulb_temp_f"),
                    "hottest_skin_temperature_f": asset_info.get("hottestSkinTemperature"),
                    "wet_bulb_temp_c":  round(((cooling_tower_analysis.get("system") or {}).get("wet_bulb_temp_f") - 32) * 5 / 9, 2)
                                        if (cooling_tower_analysis.get("system") or {}).get("wet_bulb_temp_f") is not None
                                        else (cooling_tower_analysis.get("system") or {}).get("dissolved_oxygen", {}).get("wet_bulb_temp_c"),
                } if isinstance(cooling_tower_analysis, dict) else None,
            },
            "table_data":              table_data,
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
        inhibited_salts = _get_inhibited_salts(doc.get("raw_material_chemistry"))

        if not results:
            raise ValueError(f"No grid results saved for run_id: {run_id}")

        sample_si = results[0].get("saturation_indices", {})
        available = list(sample_si.keys())

        if not available:
            raise ValueError(
                f"No saturation indices in saved results for run_id: {run_id}. "
                f"The original PHREEQC run may have failed — please re-run the analysis."
            )

        salt_id_lower = salt_id.lower()

        resolved_salt = None
        for k in available:
            if k.lower() == salt_id_lower:
                resolved_salt = k
                break

        if resolved_salt is None:
            raise ValueError(
                f"Salt '{salt_id}' not found in saved results for this water chemistry. "
                f"PHREEQC only calculates SI for minerals whose required ions are present in the water. "
                f"Available salts ({len(available)}): {available}"
            )

        # Re-color for resolved salt
        # Rebuild req from saved doc to re-apply dynamic colors
        saved_req = {
            "raw_material_chemistry": doc.get("raw_material_chemistry"),
            "product_blend":          doc.get("product_blend"),
            "product":                doc.get("product"),
            "dosage_ppm":             doc.get("dosage_ppm", 2.0),
        }
        # Re-run dynamic color calculation with saved chemistry
        # Enrich product_blend with raw material data from DB (if needed)
        saved_req = await self._enrich_product_blend_from_db(saved_req)
        results = self._apply_dynamic_colors(results, saved_req, resolved_salt)
        for r in results:
            si_info = r["saturation_indices"].get(resolved_salt)
            if si_info is None:
                r["color_code"] = "error"

        # Determine requested salts from DB (saved salts_of_interest + current salt_id)
        saved_salts_of_interest = doc.get("salts_of_interest") or []
        saved_salt_id           = doc.get("salt_id") or ""
        all_requested_in_doc    = list(set(
            ([saved_salt_id] if saved_salt_id else []) +
            ([salt_id] if salt_id else []) +
            saved_salts_of_interest
        ))

        # Filter available_salts to only user-requested salts
        phreeqc_lower = {k.lower(): k for k in available}
        user_available_salts: List[str] = sorted(set(
            phreeqc_lower[s.lower()]
            for s in all_requested_in_doc
            if s.lower() in phreeqc_lower
        ))

        chart_data = self._build_chart_data(
            results, resolved_salt, temp_unit,
            requested_salts=all_requested_in_doc,
        )
        table_data = self._build_table_data(results, resolved_salt, temp_unit)
        summary    = self._summary(results)

        await db.db["saturation_runs"].update_one(
            {"run_id": run_id},
            {"$set": {
                "active_salt_id": resolved_salt,
                "chart_data":     chart_data,
                "table_data":     table_data,
                "summary":        summary,
                "grid_results":   results,
            }},
        )

        return {
            "run_id":          run_id,
            "salt_id":         resolved_salt,
            "chart_data":      chart_data,
            "table_data":      table_data,
            "thresholds":      thresholds,
            "summary":         summary,
            "available_salts": user_available_salts,
            "grid_results":    results,
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
        Strategy: parse .dat file → fallback to minimal PHREEQC run.
        """
        salts = self.phreeqc.parse_phases_from_dat_file(self.phreeqc.phreeqc_dat)

        if not salts:
            logger.info("phreeqc.dat yielded no minerals — trying pitzer.dat")
            salts = self.phreeqc.parse_phases_from_dat_file(self.phreeqc.pitzer_dat)

        if salts:
            logger.info(f"Fetched {len(salts)} salts by parsing PHASES section from .dat file")
            return salts

        logger.warning("Direct .dat PHASES parse returned no results — falling back to PHREEQC simulation")
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











