#!/usr/bin/env python3
"""
Test AA/AMPS color with PRODUCT BLEND scenario
(the user is using a product, not just raw material directly)
"""
import sys
sys.path.insert(0, r'c:\Users\shaikat\Desktop\jimgreen vps\jimgreen-Ai-Backend - new feature added-final\backend')

import re
from typing import Any, Dict, List, Optional, Tuple

def _to_float(v, default=5.0):
    try:
        if isinstance(v, str):
            v = v.replace("%", "").strip()
        return float(v)
    except (TypeError, ValueError):
        return default

def _parse_applicable_ionic_strength(app_is_str):
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
    except:
        return 0.0, 999.0

def _evaluate_formula(formula_str, sr_val):
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
        
        print(f"  Normalized formula: '{f}'")

        # 1. Power: A * sr^B
        mp = re.search(r'([\d.]+)\s*\*?\s*sr\s*\^?\s*([\d.]+)', f)
        if mp:
            a = float(mp.group(1))
            b = float(mp.group(2))
            print(f"  Power match: a={a}, b={b}")
            if b not in (1.0, 2.0) and a > 0 and b > 0:
                dose = a * (sr_val ** b)
                return round(dose, 6)

        # 2. Quadratic
        mq = re.search(
            r'([\d.]+)\s*\*?\s*sr\s*\^?\s*2\s*([+\-])\s*([\d.]+)\s*\*?\s*sr\s*([+\-])\s*([\d.]+)',
            f
        )
        if mq:
            a = float(mq.group(1))
            b = float(mq.group(3)) * (1 if mq.group(2) == '+' else -1)
            c = float(mq.group(5)) * (1 if mq.group(4) == '+' else -1)
            dose = a * (sr_val ** 2) + b * sr_val + c
            print(f"  Quadratic match: a={a}, b={b}, c={c}")
            return round(dose, 6)

        # 3. Linear
        ml = re.search(r'([\d.]+)\s*\*?\s*sr(?:\s*([+\-])\s*([\d.]+))?', f)
        if ml:
            a = float(ml.group(1))
            b = 0.0
            if ml.group(3):
                b = float(ml.group(3)) * (1 if ml.group(2) == '+' else -1)
            dose = a * sr_val + b
            print(f"  Linear match: a={a}, b={b}")
            return round(dose, 6)
            
    except Exception as e:
        print(f"  Error: {e}")
    return None

# Formulas from user's AA/AMPS payload
aa_amps_formulas = [
    ("Hydroxyapatite", "<0.1", "Dose = 1.0947x((SR(Hydroxyapatite))^0.1038)"),
    ("Hydroxyapatite", "0.1-0.5", "Dose = 1.0947x((SR(Hydroxyapatite))^0.1038)"),
]

# HEDP formulas from test_payload_with_colors.json
hedp_formulas = [
    ("Calcite", "<0.1", "Dose = (0.0001 x SR^2) + (0.0376 x SR) + 0.2175"),
    ("Calcite", "0.1-0.5", "Dose = (0.0001 x SR^2) + (0.0376 x SR) + 0.2175"),
    ("Gypsum", "<0.5", "Dose = (0.025 x SR) + 0.15"),
]

# Test ionic strengths and SR values
test_cases = [
    ("IS=0.004", 0.004618, "Hydroxyapatite", -1.82, 0.015),   # Low SI, SR < 1
    ("IS=0.004 high SI", 0.004618, "Hydroxyapatite", 7.67, 46800000.0),  # Very high SI
    ("IS=0.08", 0.08, "Hydroxyapatite", 2.5, 316.0),           # Mid range
]

user_dosage = 2.0
band_lower = 10.0
band_upper = 5.0

print("=" * 70)
print("AA/AMPS Formula Evaluation Tests")
print("=" * 70)

for case_name, ionic_strength, mineral, si_val, sr_val in test_cases:
    print(f"\nCase: {case_name}")
    print(f"  Ionic Strength: {ionic_strength}")
    print(f"  Mineral: {mineral}, SI={si_val}, SR={sr_val:.4f}")
    
    # Check which formula applies
    matched_formula = None
    for salt, app_is_str, formula in aa_amps_formulas:
        if salt.lower() == mineral.lower():
            min_is, max_is = _parse_applicable_ionic_strength(app_is_str)
            if ionic_strength >= min_is and ionic_strength <= max_is:
                matched_formula = formula
                print(f"  Matched formula for IS range {app_is_str}: {formula}")
                break
    
    if matched_formula:
        # Apply SR > 10000 → use SI
        formula_input = si_val if sr_val > 10000 else sr_val
        print(f"  Formula input (SR>10000 uses SI): {formula_input}")
        
        dose_req = _evaluate_formula(matched_formula, formula_input)
        print(f"  Dose required: {dose_req}")
        
        if dose_req is not None:
            green_thresh = user_dosage * (1 - band_lower / 100.0)
            yellow_thresh = user_dosage * (1 + band_upper / 100.0)
            
            if dose_req <= green_thresh:
                color = "GREEN"
            elif dose_req <= yellow_thresh:
                color = "YELLOW"
            else:
                color = "RED"
            
            print(f"  Thresholds: green<={green_thresh}, yellow<={yellow_thresh}")
            print(f"  Color: {color}")
        else:
            color = "GREEN" if sr_val < 1 else "RED"
            print(f"  Formula failed, fallback: {color}")
    else:
        color = "GREEN" if sr_val < 1 else "RED"
        print(f"  No matching formula, base color: {color}")

print("\n" + "=" * 70)
print("HEDP Calcite Formula Test")
print("=" * 70)

mineral = "Calcite"
ionic_strength = 0.08
si_val = 1.36
sr_val = 10**si_val

print(f"\nCalcite SI={si_val}, SR={sr_val:.4f}, IS={ionic_strength}")
for salt, app_is_str, formula in hedp_formulas:
    if salt.lower() == mineral.lower():
        min_is, max_is = _parse_applicable_ionic_strength(app_is_str)
        if ionic_strength >= min_is and ionic_strength <= max_is:
            formula_input = sr_val
            print(f"Matched formula ({app_is_str}): {formula}")
            dose_req = _evaluate_formula(formula, formula_input)
            print(f"Dose required: {dose_req}")
            if dose_req is not None:
                green_thresh = user_dosage * (1 - band_lower / 100.0)
                yellow_thresh = user_dosage * (1 + band_upper / 100.0)
                if dose_req <= green_thresh:
                    color = "GREEN"
                elif dose_req <= yellow_thresh:
                    color = "YELLOW"
                else:
                    color = "RED"
                print(f"Color: {color}")
            break
