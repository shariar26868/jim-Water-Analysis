#!/usr/bin/env python3
import re

def _evaluate_formula(formula_str: str, sr_val: float):
    if not formula_str or sr_val is None:
        return None
    try:
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

        print(f"Normalized formula for evaluation: '{f}'")

        # ── 1. Power: A * sr^B (non-integer exponent) ────────────────────
        mp = re.search(r'([\d.]+)\s*\*?\s*sr\s*\^?\s*([\d.]+)', f)
        if mp:
            a = float(mp.group(1))
            b = float(mp.group(2))
            print(f"Matched Power pattern: a={a}, b={b}")
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
        print(f"Error evaluating: {e}")
    return None

formula = "Dose = 1.0947x((SR(Hydroxyapatite))^0.1038)"
sr_values = [0.1, 1.0, 10.0, 100.0, 1000.0, 10000.0]
for sr in sr_values:
    dose = _evaluate_formula(formula, sr)
    print(f"SR = {sr} -> Dose required = {dose}\n")
