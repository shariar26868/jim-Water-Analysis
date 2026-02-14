"""
Cooling Tower Calculations Service
Handles all cooling tower-specific calculations
"""

import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


class CoolingTowerService:
    """
    Cooling Tower operational calculations
    
    Includes:
    - Cycles of Concentration (CoC)
    - Evaporation Rate
    - Blowdown Rate
    - Makeup Rate
    - Cooling Tower Range
    - Approach Temperature
    - Tower Efficiency
    - Heat Load
    - Cooling Tons conversions
    """
    
    # ========================================
    # HELPER
    # ========================================
    @staticmethod
    def get_param_value(params: Dict[str, Any], key: str, default: float = 0.0) -> float:
        """Safely extract numeric value"""
        val = params.get(key)
        if val is None:
            return default
        if isinstance(val, (int, float)):
            return float(val)
        if isinstance(val, dict):
            return float(val.get("value", default))
        return default
    
    # ========================================
    # 1. CYCLES OF CONCENTRATION (CoC)
    # ========================================
    async def calculate_coc(
        self,
        base_water: Dict[str, Any],
        concentrated_water: Dict[str, Any],
        tracer_ion: str = "Calcium"
    ) -> Dict[str, Any]:
        """
        Calculate Cycles of Concentration
        
        Formula: CoC = Concentrated Ion Value / Base Ion Value
        
        Common tracer ions: Calcium, Magnesium, Silica, TDS
        """
        try:
            base_value = self.get_param_value(base_water, tracer_ion, 0.0)
            conc_value = self.get_param_value(concentrated_water, tracer_ion, 0.0)
            
            if base_value == 0:
                logger.warning(f"CoC calculation: base {tracer_ion} is zero")
                return {
                    "coc": None,
                    "error": f"Base {tracer_ion} is zero"
                }
            
            coc = conc_value / base_value
            
            logger.info(f"Cycles of Concentration: {coc:.2f} (using {tracer_ion})")
            
            return {
                "coc": round(coc, 2),
                "tracer_ion": tracer_ion,
                "base_value": base_value,
                "concentrated_value": conc_value
            }
            
        except Exception as e:
            logger.error(f"CoC calculation failed: {e}")
            raise
    
    # ========================================
    # 2. EVAPORATION RATE (Cooling Tower)
    # ========================================
    async def calculate_evaporation_rate(
        self,
        recirculation_rate_gpm: float,
        delta_t_f: float,
        evaporation_factor_percent: float = 85.0
    ) -> Dict[str, Any]:
        """
        Evaporation Rate
        
        Formula: 0.01 × Recirculation Rate × (Delta T / 10) × Evaporation Factor
        
        Args:
            recirculation_rate_gpm: Gallons per minute
            delta_t_f: Temperature difference (°F) - Cooling Tower Range
            evaporation_factor_percent: Typically 80-90%
        """
        try:
            evap_factor = evaporation_factor_percent / 100.0
            
            evap_rate_gpm = 0.01 * recirculation_rate_gpm * (delta_t_f / 10.0) * evap_factor
            
            logger.info(f"Evaporation Rate: {evap_rate_gpm:.2f} gpm")
            
            return {
                "evaporation_rate_gpm": round(evap_rate_gpm, 2),
                "recirculation_rate_gpm": recirculation_rate_gpm,
                "delta_t_f": delta_t_f,
                "evaporation_factor_percent": evaporation_factor_percent
            }
            
        except Exception as e:
            logger.error(f"Evaporation rate calculation failed: {e}")
            raise
    
    # ========================================
    # 3. BLOWDOWN RATE (Cooling Tower)
    # ========================================
    async def calculate_blowdown_rate(
        self,
        evaporation_rate_gpm: float,
        coc: float
    ) -> Dict[str, Any]:
        """
        Blowdown Rate
        
        Formula: Blowdown = Evaporation Rate / (CoC - 1)
        """
        try:
            if coc <= 1:
                logger.warning("Blowdown calculation: CoC must be > 1")
                return {
                    "blowdown_rate_gpm": None,
                    "error": "CoC must be greater than 1"
                }
            
            blowdown_rate = evaporation_rate_gpm / (coc - 1)
            
            logger.info(f"Blowdown Rate: {blowdown_rate:.2f} gpm")
            
            return {
                "blowdown_rate_gpm": round(blowdown_rate, 2),
                "evaporation_rate_gpm": evaporation_rate_gpm,
                "coc": coc
            }
            
        except Exception as e:
            logger.error(f"Blowdown rate calculation failed: {e}")
            raise
    
    # ========================================
    # 4. MAKEUP RATE (Cooling Tower)
    # ========================================
    async def calculate_makeup_rate(
        self,
        evaporation_rate_gpm: float,
        blowdown_rate_gpm: float,
        recirculation_rate_gpm: float,
        drift_percent: float = 0.1
    ) -> Dict[str, Any]:
        """
        Makeup Rate
        
        Formula: Makeup = Evaporation + Blowdown + Drift
        
        Drift is typically 0.1% of recirculation rate
        """
        try:
            drift_rate_gpm = recirculation_rate_gpm * (drift_percent / 100.0)
            
            makeup_rate = evaporation_rate_gpm + blowdown_rate_gpm + drift_rate_gpm
            
            logger.info(f"Makeup Rate: {makeup_rate:.2f} gpm")
            
            return {
                "makeup_rate_gpm": round(makeup_rate, 2),
                "evaporation_rate_gpm": evaporation_rate_gpm,
                "blowdown_rate_gpm": blowdown_rate_gpm,
                "drift_rate_gpm": round(drift_rate_gpm, 2),
                "drift_percent": drift_percent
            }
            
        except Exception as e:
            logger.error(f"Makeup rate calculation failed: {e}")
            raise
    
    # ========================================
    # 5. COOLING TOWER RANGE
    # ========================================
    async def calculate_tower_range(
        self,
        hot_water_temp_f: float,
        cold_water_temp_f: float
    ) -> Dict[str, Any]:
        """
        Cooling Tower Range
        
        Formula: Range (Delta T) = Hot Water Temp - Cold Water Temp
        """
        try:
            range_f = hot_water_temp_f - cold_water_temp_f
            
            logger.info(f"Cooling Tower Range: {range_f:.2f} °F")
            
            return {
                "range_f": range_f,
                "hot_water_temp_f": hot_water_temp_f,
                "cold_water_temp_f": cold_water_temp_f
            }
            
        except Exception as e:
            logger.error(f"Tower range calculation failed: {e}")
            raise
    
    # ========================================
    # 6. APPROACH TEMPERATURE
    # ========================================
    async def calculate_approach_temperature(
        self,
        cold_water_temp_f: float,
        wet_bulb_temp_f: float
    ) -> Dict[str, Any]:
        """
        Approach Temperature
        
        Formula: Approach = Cold Water Temp - Wet Bulb Temp
        """
        try:
            approach_f = cold_water_temp_f - wet_bulb_temp_f
            
            logger.info(f"Approach Temperature: {approach_f:.2f} °F")
            
            return {
                "approach_f": approach_f,
                "cold_water_temp_f": cold_water_temp_f,
                "wet_bulb_temp_f": wet_bulb_temp_f
            }
            
        except Exception as e:
            logger.error(f"Approach temperature calculation failed: {e}")
            raise
    
    # ========================================
    # 7. COOLING TOWER EFFICIENCY
    # ========================================
    async def calculate_tower_efficiency(
        self,
        range_f: float,
        approach_f: float
    ) -> Dict[str, Any]:
        """
        Tower Efficiency
        
        Formula: Efficiency = (Range / (Range + Approach)) × 100
        """
        try:
            if (range_f + approach_f) == 0:
                logger.warning("Tower efficiency: denominator is zero")
                return {
                    "efficiency_percent": None,
                    "error": "Range + Approach is zero"
                }
            
            efficiency = (range_f / (range_f + approach_f)) * 100
            
            logger.info(f"Tower Efficiency: {efficiency:.2f}%")
            
            return {
                "efficiency_percent": round(efficiency, 2),
                "range_f": range_f,
                "approach_f": approach_f
            }
            
        except Exception as e:
            logger.error(f"Tower efficiency calculation failed: {e}")
            raise
    
    # ========================================
    # 8. HEAT LOAD
    # ========================================
    async def calculate_heat_load(
        self,
        recirculation_rate_gpm: float,
        range_f: float
    ) -> Dict[str, Any]:
        """
        Heat Load
        
        Formula: Q = 500 × Recirculation Rate × Range
        """
        try:
            heat_load_btu_hr = 500 * recirculation_rate_gpm * range_f
            
            logger.info(f"Heat Load: {heat_load_btu_hr:,.0f} BTU/hr")
            
            return {
                "heat_load_btu_hr": round(heat_load_btu_hr, 0),
                "recirculation_rate_gpm": recirculation_rate_gpm,
                "range_f": range_f
            }
            
        except Exception as e:
            logger.error(f"Heat load calculation failed: {e}")
            raise
    
    # ========================================
    # 9. COOLING TONS CONVERSION
    # ========================================
    async def tons_to_recirculation_rate(
        self,
        cooling_tons: float,
        range_f: float
    ) -> Dict[str, Any]:
        """
        Convert Cooling Tons to Recirculation Rate
        
        Formula: Recirculation Rate = (30 × Tons) / Range
        """
        try:
            if range_f == 0:
                logger.warning("Tons conversion: range is zero")
                return {
                    "recirculation_rate_gpm": None,
                    "error": "Range is zero"
                }
            
            recirc_rate = (30 * cooling_tons) / range_f
            
            logger.info(f"Recirculation Rate: {recirc_rate:.2f} gpm")
            
            return {
                "recirculation_rate_gpm": round(recirc_rate, 2),
                "cooling_tons": cooling_tons,
                "range_f": range_f
            }
            
        except Exception as e:
            logger.error(f"Tons to GPM conversion failed: {e}")
            raise
    
    async def recirculation_rate_to_tons(
        self,
        recirculation_rate_gpm: float,
        range_f: float
    ) -> Dict[str, Any]:
        """
        Convert Recirculation Rate to Cooling Tons
        
        Formula: Tons = (Recirculation Rate × Range) / 30
        """
        try:
            cooling_tons = (recirculation_rate_gpm * range_f) / 30
            
            logger.info(f"Cooling Tons: {cooling_tons:.2f}")
            
            return {
                "cooling_tons": round(cooling_tons, 2),
                "recirculation_rate_gpm": recirculation_rate_gpm,
                "range_f": range_f
            }
            
        except Exception as e:
            logger.error(f"GPM to Tons conversion failed: {e}")
            raise
    
    # ========================================
    # 10. CHEMICAL DOSAGE CALCULATIONS
    # ========================================
    async def calculate_chemical_required_per_day(
        self,
        product_dosage_ppm: float,
        blowdown_rate_gpm: float
    ) -> Dict[str, Any]:
        """
        Chemical Required Per Day
        
        Formula: Chemical (lbs/day) = Dosage (ppm) × Million lbs Blowdown/day
        
        Where Million lbs BD/day = BD (gpm) × 60 × 24 × 8.34 / 1,000,000
        """
        try:
            million_lbs_bd_per_day = (blowdown_rate_gpm * 60 * 24 * 8.34) / 1_000_000
            
            chemical_lbs_per_day = product_dosage_ppm * million_lbs_bd_per_day
            
            logger.info(f"Chemical Required: {chemical_lbs_per_day:.2f} lbs/day")
            
            return {
                "chemical_lbs_per_day": round(chemical_lbs_per_day, 2),
                "product_dosage_ppm": product_dosage_ppm,
                "blowdown_rate_gpm": blowdown_rate_gpm,
                "million_lbs_bd_per_day": round(million_lbs_bd_per_day, 4)
            }
            
        except Exception as e:
            logger.error(f"Chemical dosage calculation failed: {e}")
            raise
    
    async def calculate_chemical_required_per_year(
        self,
        chemical_lbs_per_day: float,
        operating_days_per_year: int = 350
    ) -> Dict[str, Any]:
        """
        Chemical Required Per Year
        
        Formula: Chemical (lbs/year) = Chemical (lbs/day) × Operating Days
        """
        try:
            chemical_lbs_per_year = chemical_lbs_per_day * operating_days_per_year
            
            logger.info(f"Chemical Required: {chemical_lbs_per_year:,.0f} lbs/year")
            
            return {
                "chemical_lbs_per_year": round(chemical_lbs_per_year, 0),
                "chemical_lbs_per_day": chemical_lbs_per_day,
                "operating_days_per_year": operating_days_per_year
            }
            
        except Exception as e:
            logger.error(f"Annual chemical calculation failed: {e}")
            raise
    
    async def calculate_chemical_cost(
        self,
        product_dosage_ppm: float,
        product_price_per_lb: float
    ) -> Dict[str, Any]:
        """
        Customer Use-Cost
        
        Formula: $ / Million lbs BD = ppm × $/lb
        """
        try:
            cost_per_million_lbs = product_dosage_ppm * product_price_per_lb
            
            logger.info(f"Chemical Cost: ${cost_per_million_lbs:.2f} per million lbs BD")
            
            return {
                "cost_per_million_lbs_bd": round(cost_per_million_lbs, 2),
                "product_dosage_ppm": product_dosage_ppm,
                "product_price_per_lb": product_price_per_lb
            }
            
        except Exception as e:
            logger.error(f"Chemical cost calculation failed: {e}")
            raise
    
    # ========================================
    # COMPREHENSIVE TOWER ANALYSIS
    # ========================================
    async def calculate_tower_water_balance(
        self,
        recirculation_rate_gpm: float,
        hot_water_temp_f: float,
        cold_water_temp_f: float,
        wet_bulb_temp_f: float,
        coc: float,
        drift_percent: float = 0.1,
        evaporation_factor_percent: float = 85.0
    ) -> Dict[str, Any]:
        """
        Complete water balance calculation for cooling tower
        """
        try:
            logger.info("💧 Calculating complete tower water balance")
            
            results = {}
            
            # 1. Range
            range_result = await self.calculate_tower_range(hot_water_temp_f, cold_water_temp_f)
            results["range"] = range_result
            range_f = range_result["range_f"]
            
            # 2. Approach
            approach_result = await self.calculate_approach_temperature(cold_water_temp_f, wet_bulb_temp_f)
            results["approach"] = approach_result
            approach_f = approach_result["approach_f"]
            
            # 3. Efficiency
            efficiency_result = await self.calculate_tower_efficiency(range_f, approach_f)
            results["efficiency"] = efficiency_result
            
            # 4. Evaporation
            evap_result = await self.calculate_evaporation_rate(
                recirculation_rate_gpm,
                range_f,
                evaporation_factor_percent
            )
            results["evaporation"] = evap_result
            evap_rate = evap_result["evaporation_rate_gpm"]
            
            # 5. Blowdown
            bd_result = await self.calculate_blowdown_rate(evap_rate, coc)
            results["blowdown"] = bd_result
            bd_rate = bd_result["blowdown_rate_gpm"]
            
            # 6. Makeup
            makeup_result = await self.calculate_makeup_rate(
                evap_rate,
                bd_rate,
                recirculation_rate_gpm,
                drift_percent
            )
            results["makeup"] = makeup_result
            
            # 7. Heat Load
            heat_result = await self.calculate_heat_load(recirculation_rate_gpm, range_f)
            results["heat_load"] = heat_result
            
            # 8. Cooling Tons
            tons_result = await self.recirculation_rate_to_tons(recirculation_rate_gpm, range_f)
            results["cooling_tons"] = tons_result
            
            logger.info("✅ Tower water balance complete")
            
            return results
            
        except Exception as e:
            logger.error(f"❌ Tower water balance failed: {e}")
            raise