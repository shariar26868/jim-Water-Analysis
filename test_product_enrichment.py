"""
End-to-end verification: product_blend -> raw material enrichment -> color calculation
Simulates what happens when a product is selected in the frontend
"""
import asyncio, re
from dotenv import load_dotenv
load_dotenv()
from app.db.mongo import db
from app.services.saturation_service import SaturationService

async def main():
    await db.connect()
    svc = SaturationService()
    
    # Simulate a product_blend request with only productId and rawMaterials containing rawId
    # (as sent by frontend)
    
    # Product "Scale Inhibitor X" has HEDP at rawId=69cb4ed3e1f1a224bf609d48 (44%)
    # AA/AMPS rawId=69e343d84b3fd17d18c0a210
    
    print("=" * 60)
    print("Test: Product with AA/AMPS raw material")
    print("=" * 60)
    
    req_with_product = {
        "dosage_ppm": 5.0,
        "product_blend": {
            "productId": "test-product",
            "rawMaterials": [
                {
                    "rawId": "69e343d84b3fd17d18c0a210",  # AA/AMPS
                    "percentage": 70,
                    "nameSnapshot": "AA/AMPS"
                }
            ]
        }
    }
    
    print(f"Before enrichment: rawMaterials[0] keys = {list(req_with_product['product_blend']['rawMaterials'][0].keys())}")
    
    enriched = await svc._enrich_product_blend_from_db(req_with_product)
    
    rm_items = enriched["product_blend"]["rawMaterials"]
    print(f"After enrichment: rawMaterials[0] keys = {list(rm_items[0].keys())}")
    
    rm_data = rm_items[0].get("rawMaterialData")
    if rm_data:
        print(f"  name: {rm_data.get('commonName')}")
        print(f"  active%: {rm_data.get('activePercentage')}")
        formulas = rm_data.get("inhibitionFormulas") or rm_data.get("formulas") or []
        print(f"  formulas count: {len(formulas)}")
        for f in formulas:
            print(f"  formula: {f.get('salToInhibit')} @ IS={f.get('applicableIonicStrength')}")
    else:
        print("  ERROR: rawMaterialData is None!")
    
    print()
    print("=" * 60)
    print("Test: Simulating color calculation for Hydroxyapatite")
    print("=" * 60)
    
    # Mock grid results - simulate supersaturated Hydroxyapatite
    test_results = [
        {
            "_grid_CoC": 1.0,
            "_grid_temp": 25.0,
            "saturation_indices": {"Hydroxyapatite": {"SI": -1.82, "SR": 0.015}},
            "ionic_strength": 0.004
        },
        {
            "_grid_CoC": 2.0,
            "_grid_temp": 25.0,
            "saturation_indices": {"Hydroxyapatite": {"SI": 2.5, "SR": 316.0}},
            "ionic_strength": 0.005
        },
        {
            "_grid_CoC": 3.0,
            "_grid_temp": 35.0,
            "saturation_indices": {"Hydroxyapatite": {"SI": 3.01, "SR": 1023.0}},
            "ionic_strength": 0.007
        },
    ]
    
    colored = svc._apply_dynamic_colors(test_results, enriched, "Hydroxyapatite")
    
    print(f"dosage_ppm={req_with_product['dosage_ppm']} ppm (product dose)")
    print(f"AA/AMPS is 70% of product, 40% active")
    print(f"Effective active dose = 5.0 * 0.70 * 0.40 = {5.0*0.70*0.40:.3f} ppm")
    print()
    
    for r in colored:
        hap = r.get("saturation_indices", {}).get("Hydroxyapatite", {})
        hap_color = r.get("per_salt_colors", {}).get("Hydroxyapatite", "N/A")
        overall = r.get("color_code", "N/A")
        print(f"CoC={r['_grid_CoC']}, IS={r['ionic_strength']:.4f}, SI={hap.get('SI')}, SR={hap.get('SR')} -> Hap={hap_color}, overall={overall}")
    
    await db.disconnect()

asyncio.run(main())
