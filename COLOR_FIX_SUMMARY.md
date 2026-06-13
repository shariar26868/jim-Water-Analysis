# AA/AMPS Color Fix Summary

## Problem
Client reported: AA/AMPS product shows wrong colors (all green or all red) while HEDP works correctly.

---

## Root Causes Found & Fixed

### Bug 1: Wrong formula key (`formulas` vs `inhibitionFormulas`)
**File:** `app/services/saturation_service.py` — `process_raw_material()` (line ~6767)

- **DB stores** formulas under key: `"formulas"`
- **Code was looking for:** `"inhibitionFormulas"`
- **Result:** 0 formulas loaded → fallback logic → all SR>=1 = RED

**Fix:**
```python
# Before
formulas = rm_data.get("inhibitionFormulas") or []

# After
formulas = rm_data.get("inhibitionFormulas") or rm_data.get("formulas") or []
```

---

### Bug 2: Product blend — raw material data not fetched from DB
**File:** `app/services/saturation_service.py` — new `_enrich_product_blend_from_db()` method

When frontend sends a product-based request, `product_blend.rawMaterials` contains only:
```json
{ "rawId": "69e343d...", "percentage": 70, "nameSnapshot": "AA/AMPS" }
```

No `inhibitionFormulas`, no `activePercentage` — so `_apply_dynamic_colors` found no formulas.

**Fix:** Added `_enrich_product_blend_from_db()` async method that:
1. If `productId` given but no `rawMaterials` → fetches product doc from `products` collection
2. For each rawMaterial item without `rawMaterialData` → fetches full doc from `raw_materials` collection
3. Injects fetched data as `rawMaterialData` in the item
4. Also copies `formulas` → `inhibitionFormulas` for consistency

Called in both `run_analysis()` and `switch_salt()` before `_apply_dynamic_colors()`.

---

### Bug 3: Wrong percentage key
**File:** `app/services/saturation_service.py` — Case A in `_apply_dynamic_colors()` (line ~6909)

- **DB uses** key: `"percentage"` 
- **Code was looking for:** `"percentageInProduct"`
- **Result:** `pct_in_prod = 100%` always (default) instead of actual percentage

**Fix:**
```python
pct_in_prod = float(
    rm_item.get("percentageInProduct")
    or rm_item.get("percentage")
    or 100.0
) / 100.0
```

---

## How Color Logic Works (After Fix)

For AA/AMPS in a product:
```
effective_dose = user_dosage × (pct_in_product / 100) × (activePercentage / 100)
               = 5.0 × 0.70 × 0.40 = 1.4 ppm

dose_required = formula(SR) = 1.0947 × SR^0.1038

green_thresh  = effective_dose × (1 - bandLowerCushion%) 
yellow_thresh = effective_dose × (1 + bandUpperCushion%)

if dose_required <= green_thresh  → GREEN  (treatment sufficient)
if dose_required <= yellow_thresh → YELLOW (caution zone)
else                               → RED   (treatment insufficient)
```

---

## Formula Parsing Note

AA/AMPS formula: `Dose = 1.0947x((SR(Hydroxyapatite))^0.1038)`

Normalization steps:
1. `SR(Hydroxyapatite)` → `sr`
2. `1.0947x((` → `1.0947 * ((`
3. Remove parens → `1.0947 * sr ^0.1038`
4. Power match: a=1.0947, b=0.1038 ✅

---

## Commits
- `91093c3` Fix: AA/AMPS Hydroxyapatite color issue - handle missing ionic strength in overlap check
- `0b475e6` fix: _evaluate_formula implicit multiply 1.0947x( → 1.0947*(
- `8f4abf4` fix: AA/AMPS product color - fetch rawMaterial from DB + 'formulas' key support ← **LATEST**

---

## DB Structure Reference

```
raw_materials collection:
  commonName, activePercentage, bandUpperCushion, bandLowerCushion,
  formulas: [{ salToInhibit, applicableIonicStrength, formulaForInhibitionPerformance }]

products collection:
  rawMaterials: [{ rawId, percentage, nameSnapshot, costSnapshot }]
```
