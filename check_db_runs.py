#!/usr/bin/env python3
"""
Check DB runs with full grid detail - find RED points
"""
import asyncio
import os
from dotenv import load_dotenv

load_dotenv()
from app.db.mongo import db

async def main():
    await db.connect()
    col = db.db["saturation_runs"]
    
    # Find the latest run with AA/AMPS
    cursor = col.find({"raw_material_chemistry.commonName": {"$regex": "AA", "$options": "i"}}).sort("created_at", -1).limit(3)
    docs = await cursor.to_list(3)
    
    if not docs:
        print("No AA/AMPS runs found. Checking all recent runs...")
        cursor = col.find().sort("created_at", -1).limit(3)
        docs = await cursor.to_list(3)
    
    for i, doc in enumerate(docs):
        print("=" * 80)
        print(f"RUN {i}: run_id={doc.get('run_id')}")
        print(f"Created at: {doc.get('created_at')}")
        print(f"Salt selected: {doc.get('salt_id')}, dosage: {doc.get('dosage_ppm')} ppm")
        rm = doc.get("raw_material_chemistry")
        if rm:
            print(f"Raw material: {rm.get('commonName')}, active%: {rm.get('activePercentage')}")
            formulas = rm.get("inhibitionFormulas", [])
            print(f"  Inhibition formulas: {len(formulas)}")
            for f in formulas:
                print(f"    {f.get('salToInhibit')}: IS={f.get('applicableIonicStrength')}, formula={f.get('formulaForInhibitionPerformance','')[:60]}")
        
        results = doc.get("grid_results") or []
        print(f"\nTotal grid results: {len(results)}")
        
        # Find RED hydroxyapatite points
        red_hap = []
        for r in results:
            hap_color = r.get("per_salt_colors", {}).get("Hydroxyapatite")
            if hap_color and hap_color != "green":
                red_hap.append({
                    "CoC": r.get("_grid_CoC"),
                    "Temp": r.get("_grid_temp"),
                    "IS": r.get("ionic_strength"),
                    "SI": r.get("saturation_indices", {}).get("Hydroxyapatite", {}).get("SI"),
                    "SR": r.get("saturation_indices", {}).get("Hydroxyapatite", {}).get("SR"),
                    "color": hap_color,
                    "color_code": r.get("color_code"),
                })
        
        print(f"Non-green Hydroxyapatite points: {len(red_hap)}")
        for pt in red_hap[:5]:
            print(f"  CoC={pt['CoC']}, Temp={pt['Temp']}, IS={pt['IS']}, SI={pt['SI']}, SR={pt['SR']} -> {pt['color']}")
        
        if not red_hap:
            # Show a few sample points
            print("Sample points (all green):")
            for r in results[:3]:
                hap = r.get("saturation_indices", {}).get("Hydroxyapatite", {})
                print(f"  CoC={r.get('_grid_CoC')}, IS={r.get('ionic_strength'):.5f}, SI={hap.get('SI')}, color={r.get('per_salt_colors',{}).get('Hydroxyapatite')}")
    
    await db.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
