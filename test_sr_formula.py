#!/usr/bin/env python3
"""
Standalone debug script - test SR solving without PHREEQC dependency
"""
import re
import math

def _solve_for_sr(formula_str: str, dosage_ppm: float):
    """
    Solve inhibition formula for SR given a dosage value.
    """
    if not formula_str:
        return None
    try:
        f = formula_str.lower().strip()
        
        # Normalize left-hand side
        f = re.sub(r'^(y|dose|d)\s*=\s*', '', f)
        
        # Normalize SR variable
        f = re.sub(r'\bsr\s*\([^)]*\)', 'sr', f)
        
        # Normalize operators
        f = f.replace('\u00d7', '*').replace('\u00b2', '^2').replace('\u00b3', '^3')
        f = re.sub(r'(?<=[\d\w\)]) x (?=[\d\w\(sr])', ' * ', f)
        
        # standalone 'x' (variable) and 'si' → 'sr'
        f = re.sub(r'\bx\b', 'sr', f)
        f = re.sub(r'\bsi\b', 'sr', f)
        
        # Remove surrounding parentheses
        f = f.replace('(', ' ').replace(')', ' ')
        
        # Reorder "sr * coeff" → "coeff * sr"
        f = re.sub(r'\bsr\s*\*\s*([\d.]+)', r'\1 * sr', f)
        
        f = re.sub(r'\s+', ' ', f).strip()
        
        print(f"  Normalized formula: '{f}'")
        
        # 1. Try power: A * sr^B
        mp = re.search(r'([\d.]+)\s*\*?\s*sr\s*\^?\s*([\d.]+)', f)
        if mp:
            a = float(mp.group(1))
            b = float(mp.group(2))
            if b not in (1.0, 2.0) and a > 0 and b > 0:
                sr_val = (dosage_ppm / a) ** (1.0 / b)
                if sr_val > 0:
                    print(f"  ✓ Matched POWER formula: A={a}, B={b}")
                    print(f"    SR = ({dosage_ppm} / {a})^(1/{b}) = {sr_val:.6f}")
                    return round(sr_val, 6)

        # 2. Try quadratic: A * sr^2 + B * sr + C
        mq = re.search(
            r'([\d.]+)\s*\*?\s*sr\s*\^?\s*2\s*([+\-])\s*([\d.]+)\s*\*?\s*sr\s*([+\-])\s*([\d.]+)',
            f
        )
        if mq:
            a = float(mq.group(1))
            b = float(mq.group(3)) * (1 if mq.group(2) == '+' else -1)
            c = float(mq.group(5)) * (1 if mq.group(4) == '+' else -1)
            
            discriminant = b**2 - 4 * a * (c - dosage_ppm)
            if discriminant >= 0:
                sr1 = (-b + math.sqrt(discriminant)) / (2 * a)
                sr2 = (-b - math.sqrt(discriminant)) / (2 * a)
                positive_roots = [r for r in [sr1, sr2] if r > 0]
                if positive_roots:
                    sr_val = max(positive_roots)
                    print(f"  ✓ Matched QUADRATIC formula: A={a}, B={b}, C={c}")
                    print(f"    Positive root: {sr_val:.6f}")
                    return sr_val
            print(f"  ✗ Quadratic discriminant negative: {discriminant}")
            return None

        # 3. Try linear: A * sr + B
        ml = re.search(r'([\d.]+)\s*\*?\s*sr(?:\s*([+\-])\s*([\d.]+))?', f)
        if ml:
            a = float(ml.group(1))
            b = 0.0
            if ml.group(3):
                b = float(ml.group(3)) * (1 if ml.group(2) == '+' else -1)
            if a != 0:
                sr_val = (dosage_ppm - b) / a
                print(f"  ✓ Matched LINEAR formula: A={a}, B={b}")
                print(f"    SR = ({dosage_ppm} - {b}) / {a} = {sr_val:.6f}")
                return sr_val

        print(f"  ✗ Could not match any formula pattern!")

    except Exception as e:
        print(f"  ✗ Exception: {e}")
    
    return None


# Test cases
print("=" * 80)
print("Testing AA/AMPS + Hydroxyapatite Color Issue")
print("=" * 80)

test_cases = [
    {
        "name": "AA/AMPS Hydroxyapatite (Linear)",
        "formula": "Dose = 0.0358 * SR + 0.5272",
        "dosage": 2.0,
    },
    {
        "name": "AA/AMPS Hydroxyapatite variant",
        "formula": "Dose = 0.0358 × SR + 0.5272",
        "dosage": 2.0,
    },
    {
        "name": "Common Quadratic",
        "formula": "Dose = 0.002 * SR^2 + 0.05 * SR + 0.3",
        "dosage": 2.0,
    },
]

for test in test_cases:
    print(f"\n--- Test: {test['name']} ---")
    print(f"Formula: {test['formula']}")
    print(f"Dosage: {test['dosage']} ppm")
    
    sr = _solve_for_sr(test['formula'], test['dosage'])
    
    if sr is not None:
        print(f"\n✓ BreakpointSR calculated: {sr:.6f}")
        
        # Calculate color thresholds
        band_lower = 5.0
        band_upper = 5.0
        green_thresh = sr * (1 - band_lower / 100.0)
        red_thresh = sr * (1 + band_upper / 100.0)
        
        print(f"\nColor Thresholds:")
        print(f"  GREEN if SR < {green_thresh:.6f}")
        print(f"  YELLOW if {green_thresh:.6f} ≤ SR < {red_thresh:.6f}")
        print(f"  RED if SR ≥ {red_thresh:.6f}")
        
        # Test some SR values
        test_sr_values = [1.5, 2.5, 3.0, 3.5, 4.0]
        print(f"\nColor assignments at different SR values:")
        for test_sr in test_sr_values:
            if test_sr < green_thresh:
                color = "GREEN"
            elif test_sr >= red_thresh:
                color = "RED"
            else:
                color = "YELLOW"
            print(f"  SR={test_sr:.1f} → {color}")
    else:
        print(f"\n✗ Failed to parse formula!")

print("\n" + "=" * 80)
print("Analysis Complete")
print("=" * 80)
