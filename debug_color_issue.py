#!/usr/bin/env python3
"""
Debug script to identify why AA/AMPS + Hydroxyapatite stays red
"""
import asyncio
import json
from app.services.saturation_service import SaturationService

async def debug_color_issue():
    """Check if AA/AMPS formulas are being loaded correctly"""
    
    service = SaturationService()
    
    # Simulate the _apply_dynamic_colors method with debugging
    test_results = [
        {
            "coc": 2.0,
            "temperature": 110.0,
            "saturation_indices": {
                "Hydroxyapatite": {
                    "SI": 0.5,
                    "SR": 3.16  # 10^0.5 ≈ 3.16
                }
            },
            "ionic_strength": 0.08
        }
    ]
    
    # Simulate AA/AMPS raw material request
    test_req = {
        "raw_material_chemistry": {
            "inhibitionFormulas": [
                {
                    "salToInhibit": "Hydroxyapatite",
                    "formulaForInhibitionPerformance": "Dose = 0.0358 * SR + 0.5272",
                    "applicableIonicStrength": "0.05-0.15",
                    "bandLowerCushion": "5%",
                    "bandUpperCushion": "5%"
                }
            ]
        },
        "dosage_ppm": 2.0,
        "product_blend": None
    }
    
    print("=" * 80)
    print("DEBUG: AA/AMPS + Hydroxyapatite Color Assignment")
    print("=" * 80)
    print(f"\nInput Dosage: {test_req['dosage_ppm']} ppm")
    print(f"Result SR (Hydroxyapatite): {test_results[0]['saturation_indices']['Hydroxyapatite']['SR']}")
    print(f"Ionic Strength: {test_results[0]['ionic_strength']}")
    
    # Test the _solve_for_sr method
    formula = test_req["raw_material_chemistry"]["inhibitionFormulas"][0]["formulaForInhibitionPerformance"]
    breakpoint_sr = service._solve_for_sr(formula, test_req["dosage_ppm"])
    
    print(f"\n--- SR Formula Parsing ---")
    print(f"Formula: {formula}")
    print(f"Calculated BreakpointSR: {breakpoint_sr}")
    
    if breakpoint_sr:
        band_lower = 5.0
        band_upper = 5.0
        green_thresh = breakpoint_sr * (1 - band_lower / 100.0)
        red_thresh = breakpoint_sr * (1 + band_upper / 100.0)
        
        print(f"\n--- Color Thresholds ---")
        print(f"Green threshold (SR < {green_thresh:.4f})")
        print(f"Red threshold (SR >= {red_thresh:.4f})")
        
        sr_val = test_results[0]['saturation_indices']['Hydroxyapatite']['SR']
        if sr_val < green_thresh:
            color = "GREEN"
        elif sr_val >= red_thresh:
            color = "RED"
        else:
            color = "YELLOW"
        
        print(f"\n--- Result ---")
        print(f"SR Value: {sr_val:.4f}")
        print(f"Assigned Color: {color}")
    else:
        print("\n❌ ERROR: Failed to parse breakpoint SR from formula!")
        print("This is likely why the color isn't changing!")
    
    # Now test the full color application
    print("\n" + "=" * 80)
    print("Testing full _apply_dynamic_colors method")
    print("=" * 80)
    
    try:
        colored_results = service._apply_dynamic_colors(test_results, test_req, "Hydroxyapatite")
        print(f"\nColor assigned: {colored_results[0]['color_code']}")
        print(f"Per-salt colors: {colored_results[0]['per_salt_colors']}")
    except Exception as e:
        print(f"\n❌ ERROR in _apply_dynamic_colors: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(debug_color_issue())
