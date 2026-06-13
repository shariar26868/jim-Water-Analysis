#!/usr/bin/env python3
"""
Check actual cushion values stored in DB and how they affect color thresholds
"""
import asyncio
import os
from dotenv import load_dotenv

load_dotenv()
from app.db.mongo import db

async def main():
    await db.connect()
    col = db.db["saturation_runs"]
    
    # Get the AA/AMPS run
    cursor = col.find({"raw_material_chemistry.commonName": {"$regex": "AA", "$options": "i"}}).sort("created_at", -1).limit(1)
    docs = await cursor.to_list(1)
    
    if not docs:
        print("No AA/AMPS runs found")
        await db.disconnect()
        return
    
    doc = docs[0]
    rm = doc.get("raw_material_chemistry", {})
    
    print("=== Raw Material Chemistry Data ===")
    print(f"Name: {rm.get('commonName')}")
    print(f"Active percentage: {rm.get('activePercentage')}%")
    print(f"bandUpperCushion: {repr(rm.get('bandUpperCushion'))}")
    print(f"bandLowerCushion: {repr(rm.get('bandLowerCushion'))}")
    
    formulas = rm.get("inhibitionFormulas", [])
    for f in formulas:
        print(f"\nFormula for {f.get('salToInhibit')}:")
        print(f"  IS range: {f.get('applicableIonicStrength')}")
        print(f"  Formula: {f.get('formulaForInhibitionPerformance')}")
        print(f"  bandUpper in formula: {repr(f.get('bandUpperCushion'))}")
        print(f"  bandLower in formula: {repr(f.get('bandLowerCushion'))}")
    
    print("\n=== Effective Cushion Values ===")
    def to_float(v, default=5.0):
        try:
            if isinstance(v, str):
                v = v.replace("%", "").strip()
            return float(v)
        except:
            return default
    
    band_lower = to_float(rm.get("bandLowerCushion"), 5.0)
    band_upper = to_float(rm.get("bandUpperCushion"), 5.0)
    print(f"band_lower_pct used: {band_lower}")
    print(f"band_upper_pct used: {band_upper}")
    
    dosage = float(doc.get("dosage_ppm", 2.0))
    green_thresh = dosage * (1 - band_lower / 100.0)
    yellow_thresh = dosage * (1 + band_upper / 100.0)
    print(f"\ndosage_ppm: {dosage}")
    print(f"green_thresh = {dosage} * (1 - {band_lower}/100) = {green_thresh}")
    print(f"yellow_thresh = {dosage} * (1 + {band_upper}/100) = {yellow_thresh}")
    
    print("\n=== RED Points with formula re-evaluation ===")
    import re
    
    def evaluate_formula(formula_str, sr_val):
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
        mp = re.search(r'([\d.]+)\s*\*?\s*sr\s*\^?\s*([\d.]+)', f)
        if mp:
            a = float(mp.group(1))
            b = float(mp.group(2))
            if b not in (1.0, 2.0) and a > 0 and b > 0:
                return a * (sr_val ** b)
        return None
    
    formula_str = formulas[0].get("formulaForInhibitionPerformance", "") if formulas else ""
    
    results = doc.get("grid_results", [])
    red_pts = [r for r in results if r.get("per_salt_colors", {}).get("Hydroxyapatite") not in ("green", None)]
    
    for r in red_pts[:5]:
        hap = r.get("saturation_indices", {}).get("Hydroxyapatite", {})
        si = hap.get("SI", 0)
        sr = hap.get("SR") or 10**si
        is_val = r.get("ionic_strength", 0)
        formula_input = si if sr > 10000 else sr
        dose_req = evaluate_formula(formula_str, formula_input)
        
        stored_color = r.get("per_salt_colors", {}).get("Hydroxyapatite")
        
        if dose_req is not None:
            if dose_req <= green_thresh:
                calc_color = "GREEN"
            elif dose_req <= yellow_thresh:
                calc_color = "YELLOW"
            else:
                calc_color = "RED"
        else:
            calc_color = "GREEN" if sr < 1 else "RED"
        
        match = "OK" if stored_color.upper() == calc_color else "MISMATCH!"
        print(f"CoC={r.get('_grid_CoC')}, IS={is_val:.5f}, SI={si:.2f}, SR={sr:.1f}")
        dose_str = f"{dose_req:.4f}" if dose_req is not None else "N/A"
        print(f"  formula_input={formula_input:.4f}, dose_req={dose_str}")
        print(f"  stored={stored_color}, calculated={calc_color} [{match}]")
    
    await db.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
