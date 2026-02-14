"""
Biological Service - Analyze biological indicators
Bacteria, pathogens, organic material
100% Dynamic - Uses database standards
"""

import logging
from typing import Dict, Any, List

from app.db.mongo import db

logger = logging.getLogger(__name__)


class BiologicalService:
    """Analyze biological indicators in water"""
    
    async def analyze(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyze biological indicators
        
        Returns:
            {
                "indicators": [
                    {
                        "indicator_name": "Bacteria_Count",
                        "value": 0,
                        "unit": "CFU/100mL",
                        "status": "Safe",
                        "risk_level": "Low"
                    },
                    ...
                ],
                "overall_status": "Safe" / "At Risk"
            }
        """
        try:
            logger.info("🦠 Analyzing biological indicators")
            
            # Biological parameter keywords
            bio_keywords = [
                "bacteria", "coliform", "e.coli", "pathogen", 
                "bod", "cod", "organic", "microb", "fecal"
            ]
            
            indicators = []
            
            # Find biological parameters
            for param_name, param_data in parameters.items():
                param_lower = param_name.lower()
                
                # Check if it's a biological parameter
                is_biological = any(keyword in param_lower for keyword in bio_keywords)
                
                if not is_biological:
                    continue
                
                value = param_data.get("value")
                unit = param_data.get("unit")
                
                # Get standard
                standard = await db.get_parameter_standard(param_name)
                
                # Determine status and risk
                if standard:
                    status, risk_level = self._assess_biological_risk(value, standard)
                else:
                    # Default assessment
                    status, risk_level = self._default_assessment(param_name, value)
                
                indicators.append({
                    "indicator_name": param_name,
                    "value": value,
                    "unit": unit,
                    "status": status,
                    "risk_level": risk_level
                })
            
            # If no biological parameters found
            if not indicators:
                logger.warning("⚠️ No biological parameters detected in sample")
                indicators = [{
                    "indicator_name": "No Data",
                    "value": "N/A",
                    "unit": None,
                    "status": "Unknown",
                    "risk_level": "Unknown"
                }]
            
            # Determine overall status
            overall_status = self._calculate_overall_status(indicators)
            
            logger.info(f"✅ Biological analysis complete - {len(indicators)} indicator(s), Status: {overall_status}")
            
            return {
                "indicators": indicators,
                "overall_status": overall_status
            }
            
        except Exception as e:
            logger.error(f"❌ Biological analysis failed: {e}")
            raise Exception(f"Biological analysis failed: {str(e)}")
    
    def _assess_biological_risk(self, value: Any, standard: Dict) -> tuple:
        """
        Assess biological risk based on standard
        
        Returns: (status, risk_level)
        """
        if not isinstance(value, (int, float)):
            return ("Unknown", "Unknown")
        
        thresholds = standard.get('thresholds', {})
        
        # For biological, lower is better
        optimal = thresholds.get('optimal', {})
        good = thresholds.get('good', {})
        warning = thresholds.get('warning', {})
        
        optimal_max = optimal.get('max', 0)
        good_max = good.get('max', 10)
        warning_max = warning.get('max', 100)
        
        if value <= optimal_max:
            return ("Safe", "Low")
        elif value <= good_max:
            return ("Acceptable", "Low")
        elif value <= warning_max:
            return ("At Risk", "Medium")
        else:
            return ("Unsafe", "High")
    
    def _default_assessment(self, param_name: str, value: Any) -> tuple:
        """
        Default assessment when no standard available
        """
        param_lower = param_name.lower()
        
        if not isinstance(value, (int, float)):
            return ("Unknown", "Unknown")
        
        # Bacteria/Coliform
        if any(x in param_lower for x in ["bacteria", "coliform", "e.coli"]):
            if value == 0:
                return ("Safe", "Low")
            elif value < 10:
                return ("Acceptable", "Low")
            elif value < 100:
                return ("At Risk", "Medium")
            else:
                return ("Unsafe", "High")
        
        # BOD/COD
        elif any(x in param_lower for x in ["bod", "cod"]):
            if value < 5:
                return ("Normal", "Low")
            elif value < 20:
                return ("Elevated", "Medium")
            else:
                return ("High", "High")
        
        # Organic material
        elif "organic" in param_lower:
            if value < 2:
                return ("Normal", "Low")
            elif value < 5:
                return ("Moderate", "Medium")
            else:
                return ("High", "High")
        
        # Default
        return ("Unknown", "Unknown")
    
    def _calculate_overall_status(self, indicators: List[Dict]) -> str:
        """
        Calculate overall biological status
        
        Returns: "Safe", "Acceptable", "At Risk", "Unsafe"
        """
        if not indicators or indicators[0]["indicator_name"] == "No Data":
            return "Unknown"
        
        # Count risk levels
        risk_counts = {
            "High": 0,
            "Medium": 0,
            "Low": 0,
            "Unknown": 0
        }
        
        for indicator in indicators:
            risk_level = indicator.get("risk_level", "Unknown")
            if risk_level in risk_counts:
                risk_counts[risk_level] += 1
        
        # Determine overall
        if risk_counts["High"] > 0:
            return "Unsafe"
        elif risk_counts["Medium"] > 0:
            return "At Risk"
        elif risk_counts["Low"] > 0:
            return "Safe"
        else:
            return "Unknown"