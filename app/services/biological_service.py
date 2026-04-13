"""
Biological Indicators Service
==============================
Assesses microbiological risk in cooling water / industrial water systems.

Factors assessed
----------------
1. Bacteria (HPC)          — Heterotrophic Plate Count if provided
2. Legionella Risk         — Temperature-based (20–45 °C danger zone)
3. Biofilm Risk            — Nutrient loading (phosphate, organic carbon, iron)
4. Algae Risk              — Nutrient + temperature driven
5. Corrosion-related MIC   — Microbiologically Influenced Corrosion indicators

Calculation methodology
-----------------------
Each indicator is scored 0–10 based on measured values or inferred conditions.
Overall status = worst individual indicator.

NOTE: This is NOT a potable-water compliance check.
      For drinking-water compliance use the Potable Water Compliance Assessment.
"""

import logging
from typing import Dict, Any, List

logger = logging.getLogger(__name__)


# ── Thresholds ────────────────────────────────────────────────────────────────
# Bacteria / HPC  (CFU/mL for cooling water — ASHRAE 188 / BSRIA BG 50)
HPC_THRESHOLDS = {
    "low":      1_000,    # < 1,000 CFU/mL  → acceptable
    "medium":  10_000,    # 1k–10k          → monitor
    "high":   100_000,    # 10k–100k        → action required
}

# Legionella (CFU/L — ASHRAE 188 / HSE ACoP L8)
LEGIONELLA_THRESHOLDS = {
    "low":     100,       # < 100 CFU/L     → acceptable
    "medium":  1_000,     # 100–1k          → investigate
    "high":   10_000,     # > 1k            → immediate action
}

# Phosphate (mg/L) — nutrient driver for biofilm / algae
PHOSPHATE_THRESHOLDS = {"low": 0.1, "medium": 0.5, "high": 2.0}

# Iron (mg/L) — MIC driver
IRON_THRESHOLDS = {"low": 0.1, "medium": 0.3, "high": 1.0}


def _get(params: Dict[str, Any], key: str, default=None):
    """Extract numeric value from nested or flat param dict."""
    val = params.get(key)
    if val is None:
        return default
    if isinstance(val, dict):
        v = val.get("value", default)
        try:
            return float(v) if v is not None else default
        except (TypeError, ValueError):
            return default
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _risk_from_thresholds(value: float, thresholds: Dict) -> str:
    if value < thresholds["low"]:
        return "Low"
    if value < thresholds["medium"]:
        return "Medium"
    if value < thresholds["high"]:
        return "High"
    return "Critical"


class BiologicalService:
    """
    Assess biological / microbiological risk in industrial water systems.

    Indicators
    ----------
    - Bacteria (HPC)     : measured CFU/mL if available
    - Legionella Risk    : measured CFU/L OR inferred from temperature
    - Biofilm Risk       : inferred from phosphate, iron, organic carbon, temperature
    - Algae Risk         : inferred from phosphate, temperature
    - MIC Risk           : inferred from iron, sulfate, pH

    Each indicator returns:
        indicator_name, value, unit, status, risk_level, basis, description
    """

    async def analyze(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        logger.info("🦠 Biological indicators analysis")

        indicators: List[Dict[str, Any]] = []

        # 1. Bacteria (HPC) ────────────────────────────────────────────────────
        hpc = _get(parameters, "Bacteria") or _get(parameters, "HPC") or _get(parameters, "Bacteria_Count")
        if hpc is not None:
            risk = _risk_from_thresholds(hpc, HPC_THRESHOLDS)
            status = "Unsafe" if risk in ("High", "Critical") else ("At Risk" if risk == "Medium" else "Acceptable")
            indicators.append({
                "indicator_name": "Heterotrophic Plate Count (HPC)",
                "value":          hpc,
                "unit":           "CFU/mL",
                "status":         status,
                "risk_level":     risk,
                "basis":          "Measured",
                "description":    "Total culturable bacteria. ASHRAE 188 action level: >10,000 CFU/mL.",
                "reference":      "ASHRAE 188 / BSRIA BG 50",
            })
        else:
            indicators.append({
                "indicator_name": "Heterotrophic Plate Count (HPC)",
                "value":          "Not tested",
                "unit":           "CFU/mL",
                "status":         "Unknown",
                "risk_level":     "Unknown",
                "basis":          "Not provided",
                "description":    "Provide 'Bacteria' or 'HPC' parameter for assessment.",
                "reference":      "ASHRAE 188 / BSRIA BG 50",
            })

        # 2. Legionella ────────────────────────────────────────────────────────
        leg = _get(parameters, "Legionella") or _get(parameters, "Legionella_pneumophila")
        temp_c = _get(parameters, "Temperature", 25.0)

        if leg is not None:
            risk   = _risk_from_thresholds(leg, LEGIONELLA_THRESHOLDS)
            status = "Unsafe" if risk in ("High", "Critical") else ("At Risk" if risk == "Medium" else "Acceptable")
            basis  = "Measured"
            desc   = "Legionella pneumophila count. HSE ACoP L8 action level: >1,000 CFU/L."
        else:
            # Infer from temperature (20–45 °C = danger zone)
            if 20 <= temp_c <= 45:
                risk   = "High" if 30 <= temp_c <= 40 else "Medium"
                status = "At Risk"
                basis  = "Inferred from temperature"
                desc   = (
                    f"Temperature {temp_c}°C is within Legionella growth range (20–45°C). "
                    "Optimal growth: 30–40°C. Recommend Legionella testing."
                )
            elif temp_c > 60:
                risk, status, basis = "Low", "Acceptable", "Inferred from temperature"
                desc = f"Temperature {temp_c}°C exceeds Legionella kill threshold (>60°C)."
            else:
                risk, status, basis = "Low", "Acceptable", "Inferred from temperature"
                desc = f"Temperature {temp_c}°C is below Legionella growth range (<20°C)."

        indicators.append({
            "indicator_name": "Legionella Risk",
            "value":          leg if leg is not None else f"{temp_c}°C (inferred)",
            "unit":           "CFU/L" if leg is not None else "°C",
            "status":         status,
            "risk_level":     risk,
            "basis":          basis,
            "description":    desc,
            "reference":      "HSE ACoP L8 / ASHRAE 188",
        })

        # 3. Biofilm Risk ──────────────────────────────────────────────────────
        phosphate = (
            _get(parameters, "Phosphate") or
            _get(parameters, "PO4") or
            _get(parameters, "Phosphorus") or 0.0
        )
        iron = _get(parameters, "Iron") or _get(parameters, "Fe") or 0.0
        toc  = _get(parameters, "TOC") or _get(parameters, "Organic_Carbon") or 0.0

        biofilm_score = 0
        biofilm_factors = []
        if phosphate > PHOSPHATE_THRESHOLDS["medium"]:
            biofilm_score += 3
            biofilm_factors.append(f"Phosphate {phosphate} mg/L (elevated nutrient)")
        elif phosphate > PHOSPHATE_THRESHOLDS["low"]:
            biofilm_score += 1
            biofilm_factors.append(f"Phosphate {phosphate} mg/L (moderate)")
        if iron > IRON_THRESHOLDS["medium"]:
            biofilm_score += 3
            biofilm_factors.append(f"Iron {iron} mg/L (MIC driver)")
        elif iron > IRON_THRESHOLDS["low"]:
            biofilm_score += 1
            biofilm_factors.append(f"Iron {iron} mg/L (moderate)")
        if toc > 5:
            biofilm_score += 2
            biofilm_factors.append(f"TOC {toc} mg/L (organic carbon)")
        if 25 <= temp_c <= 45:
            biofilm_score += 2
            biofilm_factors.append(f"Temperature {temp_c}°C (biofilm growth range)")

        if biofilm_score >= 6:
            bf_risk, bf_status = "High", "At Risk"
        elif biofilm_score >= 3:
            bf_risk, bf_status = "Medium", "Monitor"
        else:
            bf_risk, bf_status = "Low", "Acceptable"

        indicators.append({
            "indicator_name": "Biofilm Risk",
            "value":          biofilm_score,
            "unit":           "score/10",
            "status":         bf_status,
            "risk_level":     bf_risk,
            "basis":          "Inferred (phosphate, iron, TOC, temperature)",
            "description":    (
                "Biofilm formation risk based on nutrient loading and temperature. "
                + (f"Drivers: {', '.join(biofilm_factors)}" if biofilm_factors else "No significant drivers detected.")
            ),
            "reference":      "ASHRAE 188 / CTI Guidelines",
        })

        # 4. Algae Risk ────────────────────────────────────────────────────────
        algae_score = 0
        algae_factors = []
        if phosphate > 0.1:
            algae_score += 3
            algae_factors.append(f"Phosphate {phosphate} mg/L")
        nitrate = _get(parameters, "Nitrate") or _get(parameters, "NO3") or 0.0
        if nitrate > 5:
            algae_score += 2
            algae_factors.append(f"Nitrate {nitrate} mg/L")
        if 15 <= temp_c <= 35:
            algae_score += 2
            algae_factors.append(f"Temperature {temp_c}°C")

        if algae_score >= 5:
            al_risk, al_status = "High", "At Risk"
        elif algae_score >= 3:
            al_risk, al_status = "Medium", "Monitor"
        else:
            al_risk, al_status = "Low", "Acceptable"

        indicators.append({
            "indicator_name": "Algae Risk",
            "value":          algae_score,
            "unit":           "score/10",
            "status":         al_status,
            "risk_level":     al_risk,
            "basis":          "Inferred (phosphate, nitrate, temperature)",
            "description":    (
                "Algae growth risk in open cooling systems. "
                + (f"Drivers: {', '.join(algae_factors)}" if algae_factors else "No significant drivers detected.")
            ),
            "reference":      "CTI Guidelines / ASHRAE 188",
        })

        # 5. MIC (Microbiologically Influenced Corrosion) ──────────────────────
        sulfate = (
            _get(parameters, "Sulfate") or
            _get(parameters, "Sulphate") or
            _get(parameters, "SO4") or 0.0
        )
        ph = _get(parameters, "pH", 7.0)

        mic_score = 0
        mic_factors = []
        if iron > 0.3:
            mic_score += 3
            mic_factors.append(f"Iron {iron} mg/L (iron-oxidising bacteria substrate)")
        if sulfate > 200:
            mic_score += 3
            mic_factors.append(f"Sulfate {sulfate} mg/L (SRB substrate)")
        elif sulfate > 100:
            mic_score += 1
            mic_factors.append(f"Sulfate {sulfate} mg/L (moderate)")
        if ph < 6.5 or ph > 9.0:
            mic_score += 2
            mic_factors.append(f"pH {ph} (outside optimal range)")

        if mic_score >= 5:
            mic_risk, mic_status = "High", "At Risk"
        elif mic_score >= 3:
            mic_risk, mic_status = "Medium", "Monitor"
        else:
            mic_risk, mic_status = "Low", "Acceptable"

        indicators.append({
            "indicator_name": "MIC Risk (Microbiologically Influenced Corrosion)",
            "value":          mic_score,
            "unit":           "score/10",
            "status":         mic_status,
            "risk_level":     mic_risk,
            "basis":          "Inferred (iron, sulfate, pH)",
            "description":    (
                "Risk of corrosion driven by sulfate-reducing bacteria (SRB) and iron-oxidising bacteria. "
                + (f"Drivers: {', '.join(mic_factors)}" if mic_factors else "No significant drivers detected.")
            ),
            "reference":      "NACE SP0169 / ASTM G184",
        })

        # ── Overall status ────────────────────────────────────────────────────
        priority = {"Critical": 4, "High": 3, "Medium": 2, "Low": 1, "Unknown": 0}
        worst = max(indicators, key=lambda x: priority.get(x["risk_level"], 0))
        overall = worst["risk_level"]

        status_map = {
            "Critical": "Unsafe",
            "High":     "At Risk",
            "Medium":   "Monitor",
            "Low":      "Acceptable",
            "Unknown":  "Unknown",
        }

        logger.info(f"✅ Biological analysis complete — overall: {overall}")

        return {
            "assessment_title": "Biological Indicators — Cooling Water",
            "methodology": (
                "Each indicator is scored based on measured values (if provided) "
                "or inferred from water chemistry and temperature. "
                "This is NOT a potable-water compliance check — "
                "see 'Potable Water Compliance Assessment' for drinking water standards."
            ),
            "indicators":     indicators,
            "overall_status": status_map.get(overall, "Unknown"),
            "overall_risk":   overall,
        }
