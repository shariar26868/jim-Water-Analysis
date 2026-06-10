# AA/AMPS + Hydroxyapatite Color Issue - Fix Summary

## Problem
When using AA/AMPS raw material with Hydroxyapatite salt, the graph remained completely RED regardless of dosage selected, even though the SR formula was valid.

## Root Cause
In the `_apply_dynamic_colors()` method, the ionic strength overlap check was failing:
- When dataset ionic strength (IS) was 0 or missing, the overlap check would reject formulas with specified IS ranges
- Example: If dataset IS = 0 and formula required IS range of [0.05, 0.15], overlap check would fail
- Without matching formulas, the color assignment fell back to default logic: SR < 1 = green, else red
- Since typical SR values > 1, everything stayed red

## Solution Implemented
Modified the overlap check in `_apply_dynamic_colors()` (lines 6708-6719 in saturation_service.py):

```python
# Special case: if dataset IS is 0 (not calculated), assume it's applicable
if min_is == 0 and max_is == 0:
    # Dataset IS not available; assume formula is applicable
    overlaps = True
    logger.debug(f"Dataset IS is 0 (not calculated); assuming formula for {salt_to_inhibit} is applicable")
else:
    # Check normal overlap: any part of dataset IS falls within formula range
    overlaps = (min_is <= app_is_max) and (max_is >= app_is_min)
```

## Enhanced Logging
Added comprehensive logging to help debug color assignment issues:
- Info log showing active salt breakpoints when colors are applied
- Debug logs for each mineral showing:
  - SR value and calculated BreakpointSR
  - Color thresholds used
  - Final color assignment and reason

## Test Scripts Provided
- `test_sr_formula.py`: Validates SR formula parsing works correctly
- `debug_color_issue.py`: Tests the full color application logic (requires PHREEQC)

## Impact
✅ AA/AMPS + Hydroxyapatite colors should now change correctly based on dosage
✅ Formulas are applied even when ionic strength data is unavailable
✅ Easier debugging with enhanced logging for future issues

## Files Modified
- `app/services/saturation_service.py` (lines 6669-6834)
  - Fixed overlap check logic
  - Enhanced color assignment logging
