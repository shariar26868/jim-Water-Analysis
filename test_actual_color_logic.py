#!/usr/bin/env python3
import re
from typing import Any, Dict, List, Optional, Tuple

def _to_float(v, default=5.0):
    try:
        if isinstance(v, str):
            v = v.replace("%", "").strip()
        return float(v)
    except (TypeError, ValueError):
        return default

def _parse_applicable_ionic_strength(app_is_str: Optional[str]) -> Tuple[float, float]:
    if not app_is_str or isinstance(app_is_str, (int, float)):
        return 0.0, 999.0
    
    app_is_str = str(app_is_str).strip()
    
    try:
        if "<" in app_is_str:
            val = float(app_is_str.replace("<", "").replace(">", "").strip())
            return 0.0, val
        
        if ">" in app_is_str:
            val = float(app_is_str.replace("<", "").replace(">", "").strip())
            return val, 999.0
        
        if "-" in app_is_str:
            parts = app_is_str.split("-")
            if len(parts) == 2:
                return float(parts[0].strip()), float(parts[1].strip())
        
        val = float(app_is_str)
        return val, val + 0.01
    
    except (ValueError, TypeError) as e:
        return 0.0, 999.0

def _evaluate_formula(formula_str: str, sr_val: float) -> Optional[float]:
    if not formula_str or sr_val is None:
        return None
    try:
        f = formula_str.lower().strip()
        f = re.sub(r'^(y|dose|d)\s*=\s*', '', f)
        f = re.sub(r'\bsr\s*\([^)]*\)', 'sr', f)
        f = f.replace('\u00d7', '*').replace('\u00b2', '^2').replace('\u00b3', '^3')
        f = re.sub(r'(\d)x\s*\(', r'\1 * (', f)
        f = re.sub(r'(\d)x(?=[\d\s])', r'\1 *', f)
        f = re.sub(r'(?<=[\d\w\)]) x (?=[\d\w\(sr])', ' * ', f)
        f = re.sub(r'\bx\b', 'sr', f)
        f = re.sub(r'\bsi\b', 'sr', f)
        f = f.replace('(', ' ').replace(')', ' ')
        f = re.sub(r'\bsr\s*\*\s*([\d.]+)', r'\1 * sr', f)
        f = re.sub(r'\s+', ' ', f).strip()

        # 1. Power: A * sr^B
        mp = re.search(r'([\d.]+)\s*\*?\s*sr\s*\^?\s*([\d.]+)', f)
        if mp:
            a = float(mp.group(1))
            b = float(mp.group(2))
            if b not in (1.0, 2.0) and a > 0 and b > 0:
                dose = a * (sr_val ** b)
                return round(dose, 6)

        # 2. Quadratic: A * sr^2 + B * sr + C
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

        # 3. Linear: A * sr + B
        ml = re.search(r'([\d.]+)\s*\*?\s*sr(?:\s*([+\-])\s*([\d.]+))?', f)
        if ml:
            a = float(ml.group(1))
            b = 0.0
            if ml.group(3):
                b = float(ml.group(3)) * (1 if ml.group(2) == '+' else -1)
            dose = a * sr_val + b
            return round(dose, 6)

    except Exception as e:
        print(f"Error evaluating formula '{formula_str}': {e}")
    return None

def _get_inhibited_salts(raw_material_chemistry: Optional[Dict]) -> List[str]:
    if not raw_material_chemistry:
        return []
    formulas = raw_material_chemistry.get("inhibitionFormulas") or []
    return [f.get("salToInhibit", "") for f in formulas if f.get("salToInhibit")]

def _apply_dynamic_colors(
    results: List[Dict[str, Any]],
    req: Dict[str, Any],
    salt_id: Optional[str]
) -> List[Dict[str, Any]]:
    if not results:
        return results

    # 1. Determine min and max Ionic Strength for the entire dataset
    ionic_strengths = [r.get("ionic_strength", 0.0) for r in results]
    min_is = min(ionic_strengths) if ionic_strengths else 0.0
    max_is = max(ionic_strengths) if ionic_strengths else 0.0

    raw_material_data = req.get("raw_material_chemistry")
    product_data = req.get("product_blend") or req.get("product")
    user_dosage_ppm = float(req.get("dosage_ppm") or 2.0)
    
    salt_formulas: Dict[str, Tuple[str, float, float, float]] = {}

    def process_raw_material(rm_data, dosage):
        if not rm_data:
            return
        
        band_lower_pct = _to_float(rm_data.get("bandLowerCushion"), 5.0)
        band_upper_pct = _to_float(rm_data.get("bandUpperCushion"), 5.0)

        formulas = rm_data.get("inhibitionFormulas") or []
        for formula_obj in formulas:
            salt_to_inhibit = formula_obj.get("salToInhibit", "")
            if not salt_to_inhibit:
                continue
            
            app_is_str = formula_obj.get("applicableIonicStrength", "")
            app_is_min, app_is_max = _parse_applicable_ionic_strength(app_is_str)
            
            if min_is == 0 and max_is == 0:
                overlaps = True
            else:
                overlaps = (min_is <= app_is_max) and (max_is >= app_is_min)

            if not overlaps:
                continue

            formula_str = formula_obj.get("formulaForInhibitionPerformance", "")
            if not formula_str:
                continue
            
            salt_lower = salt_to_inhibit.lower()
            if salt_lower not in salt_formulas:
                salt_formulas[salt_lower] = (formula_str, dosage, band_lower_pct, band_upper_pct)

    # 3. Handle Product vs Raw Material Input
    if product_data:
        if isinstance(product_data.get("rawMaterials"), list) and product_data["rawMaterials"]:
            # Case A: blended product
            for rm_item in product_data["rawMaterials"]:
                rm_chem = rm_item.get("rawMaterialData") or rm_item.get("rawMaterialChemistry")
                if not rm_chem:
                    continue
                pct_in_prod = float(rm_item.get("percentageInProduct", 100.0)) / 100.0
                active_pct = float(rm_chem.get("activePercentage", 100.0)) / 100.0
                rm_dosage = user_dosage_ppm * pct_in_prod * active_pct
                process_raw_material(rm_chem, rm_dosage)
        elif product_data.get("rawMaterialChemistry"):
            # Case B: single raw material embedded
            rm_chem = product_data["rawMaterialChemistry"]
            active_pct = float(rm_chem.get("activePercentage", 100.0)) / 100.0
            process_raw_material(rm_chem, user_dosage_ppm * active_pct)
        elif product_data.get("inhibitionFormulas"):
            # Case C: product_blend itself has inhibitionFormulas
            process_raw_material(product_data, user_dosage_ppm)
        elif raw_material_data:
            # Fallback to raw_material_chemistry
            process_raw_material(raw_material_data, user_dosage_ppm)
    elif raw_material_data:
        # Case D: only raw_material_chemistry provided
        process_raw_material(raw_material_data, user_dosage_ppm)

    print(f"Active formulas loaded: {list(salt_formulas.keys())}")

    for r in results:
        si_detail = r.get("saturation_indices", {})
        per_salt_colors = {}

        for mineral_name, mineral_data in si_detail.items():
            si_val_raw = mineral_data.get("SI", 0.0)
            sr_val = mineral_data.get("SR")
            if sr_val is None:
                sr_val = round(10 ** si_val_raw, 6)

            # if sr_val > 10000:
            #     formula_input = si_val_raw
            # else:
            #     formula_input = sr_val
            formula_input = sr_val

            matched_formula = None
            mineral_lower = mineral_name.lower()

            for s_to_inh, formula_data in salt_formulas.items():
                if s_to_inh in mineral_lower or mineral_lower in s_to_inh:
                    matched_formula = formula_data
                    break

            if matched_formula:
                formula_str, dosage, b_lower, b_upper = matched_formula
                dose_required = _evaluate_formula(formula_str, formula_input)

                if dose_required is None:
                    c = "green" if sr_val < 1 else "red"
                else:
                    green_thresh  = dosage * (1 - b_lower / 100.0)
                    yellow_thresh = dosage * (1 + b_upper / 100.0)

                    if dose_required <= green_thresh:
                        c = "green"
                    elif dose_required <= yellow_thresh:
                        c = "yellow"
                    else:
                        c = "red"
                    
                    print(f"  {mineral_name}: SR={sr_val:.3f}, formula_input={formula_input:.3f}, dose_req={dose_required:.3f}, dosage_thresholds=[{green_thresh:.3f}, {yellow_thresh:.3f}] -> {c}")
            else:
                c = "green" if sr_val < 1 else "red"

            per_salt_colors[mineral_name] = c

        r["per_salt_colors"] = per_salt_colors
        
        target_salt = (salt_id or "").lower()
        assigned_color = "green"
        for m_name, m_color in per_salt_colors.items():
            if m_name.lower() == target_salt:
                assigned_color = m_color
                break
        else:
            if per_salt_colors:
                assigned_color = next(iter(per_salt_colors.values()))
        
        r["color_code"] = assigned_color

    return results

def main():
    test_results = [
        {
            "ionic_strength": 0.004618,
            "saturation_indices": {
                "Hydroxyapatite": {
                    "SI": 0.32,
                    "SR": 2.089
                }
            }
        },
        {
            "ionic_strength": 0.004618,
            "saturation_indices": {
                "Hydroxyapatite": {
                    "SI": 1.5,
                    "SR": 31.62
                }
            }
        },
        {
            "ionic_strength": 0.004618,
            "saturation_indices": {
                "Hydroxyapatite": {
                    "SI": 4.73,
                    "SR": 53700.0
                }
            }
        }
    ]
    
    test_req = {
        "dosage_ppm": 2.0,
        "product_blend": None,
        "raw_material_chemistry": {
            "rawMaterialId": "69e343d84b3fd17d18c0a210",
            "commonName": "AA/AMPS",
            "activeComponentName": "AA/AMPS",
            "activePercentage": 40,
            "activePercentageChemicalFormula": "AA/AMPS",
            "inhibitionFormulas": [
                {
                    "salToInhibit": "Hydroxyapatite",
                    "applicableIonicStrength": "<0.1",
                    "formulaForInhibitionPerformance": "Dose = 1.0947x((SR(Hydroxyapatite))^0.1038)"
                },
                {
                    "salToInhibit": "Hydroxyapatite",
                    "applicableIonicStrength": "0.1-0.5",
                    "formulaForInhibitionPerformance": "Dose = 1.0947x((SR(Hydroxyapatite))^0.1038)"
                }
            ],
            "bandUpperCushion": "5%",
            "bandLowerCushion": "10%"
        }
    }
    
    print("=== TEST CASE 1: Raw Material chemistry (dosage_ppm=2.0) ===")
    res = _apply_dynamic_colors(test_results, test_req, "Hydroxyapatite")
    for idx, r in enumerate(res):
        print(f"Point {idx}: SR={r['saturation_indices']['Hydroxyapatite']['SR']}, Color={r['color_code']}")

if __name__ == "__main__":
    main()
