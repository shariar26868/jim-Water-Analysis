"""
Quality Report Service - Generate water quality report
Water Quality Index, Compliance Score, Risk Factor
100% Dynamic - Uses database configuration
"""

import logging
from typing import Dict, Any

from app.db.mongo import db

logger = logging.getLogger(__name__)


class QualityReportService:
    """Generate comprehensive water quality report"""
    
    async def generate_report(
        self,
        parameters: Dict[str, Any],
        chemical_status: Dict[str, Any],
        compliance_checklist: Dict[str, Any],
        contamination_risk: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Generate quality report with:
        1. Water Quality Index (WQI)
        2. Compliance Score
        3. Risk Factor
        
        Returns:
            {
                "water_quality_index": {...},
                "compliance_score": {...},
                "risk_factor": {...}
            }
        """
        try:
            logger.info("📋 Generating water quality report")
            
            # 1. Calculate Water Quality Index
            wqi = await self._calculate_wqi(parameters, chemical_status)
            
            # 2. Calculate Compliance Score
            compliance_score = self._calculate_compliance_score(compliance_checklist)
            
            # 3. Calculate Risk Factor
            risk_factor = self._calculate_risk_factor(contamination_risk)
            
            logger.info(f"✅ Quality report generated - WQI: {wqi['score']}, Compliance: {compliance_score['percentage']}")
            
            return {
                "water_quality_index": wqi,
                "compliance_score": compliance_score,
                "risk_factor": risk_factor
            }
            
        except Exception as e:
            logger.error(f"❌ Quality report generation failed: {e}")
            raise Exception(f"Quality report generation failed: {str(e)}")
    
    async def _calculate_wqi(self, parameters: Dict, chemical_status: Dict) -> Dict[str, Any]:
        """
        Calculate Water Quality Index (WQI)
        
        WQI Formula (weighted average):
        WQI = Σ(Wi × Qi) / ΣWi
        
        Where:
        - Wi = weight of parameter i
        - Qi = quality rating of parameter i
        """
        # Get WQI configuration from database
        config = await db.get_scoring_config("water_quality_index")
        if not config:
            config = self._get_default_wqi_config()
        
        # Parameters to include in WQI
        wqi_params = [
            "pH", "TDS", "Hardness", "Alkalinity", "Chloride",
            "Sulfate", "Nitrate", "Fluoride", "Iron", "Turbidity"
        ]
        
        total_weight = 0
        weighted_sum = 0
        
        for param_name in wqi_params:
            # Find parameter (case-insensitive)
            param_key = self._find_parameter(parameters, param_name)
            
            if not param_key:
                continue
            
            value = parameters[param_key].get("value", 0)
            
            # Get standard from database
            standard = await db.get_parameter_standard(param_name)
            
            if not standard:
                continue
            
            # Get ideal value and permissible limit
            standards_data = standard.get('standards', {})
            who_standard = standards_data.get('WHO', {})
            
            ideal_value = who_standard.get('ideal', who_standard.get('min', 0))
            permissible_limit = who_standard.get('max', 100)
            
            # Calculate quality rating (Qi)
            if value <= ideal_value:
                qi = 100
            elif value <= permissible_limit:
                qi = 100 - ((value - ideal_value) / (permissible_limit - ideal_value)) * 50
            else:
                qi = 50 - ((value - permissible_limit) / permissible_limit) * 50
                qi = max(qi, 0)
            
            # Weight (Wi) - all equal for now
            weight = 1.0
            
            weighted_sum += weight * qi
            total_weight += weight
        
        # Calculate WQI
        if total_weight > 0:
            wqi_score = weighted_sum / total_weight
        else:
            wqi_score = 50.0  # Default if no parameters
        
        # Get rating
        rating = self._get_wqi_rating(wqi_score)
        
        return {
            "score": round(wqi_score, 1),
            "max_score": 100,
            "rating": rating
        }
    
    def _calculate_compliance_score(self, compliance_checklist: Dict) -> Dict[str, Any]:
        """
        Calculate compliance score as percentage
        
        Score = (Passed / Total) × 100
        """
        passed = compliance_checklist.get('passed_count', 0)
        total = (
            compliance_checklist.get('passed_count', 0) +
            compliance_checklist.get('failed_count', 0)
        )
        
        if total == 0:
            score = 0.0
            percentage = "0%"
        else:
            score = (passed / total) * 100
            percentage = f"{score:.1f}%"
        
        # Get rating
        if score >= 95:
            rating = "Excellent"
        elif score >= 85:
            rating = "Very Good"
        elif score >= 75:
            rating = "Good"
        elif score >= 60:
            rating = "Fair"
        else:
            rating = "Poor"
        
        return {
            "score": round(score, 1),
            "percentage": percentage,
            "rating": rating
        }
    
    def _calculate_risk_factor(self, contamination_risk: Dict) -> Dict[str, Any]:
        """
        Calculate risk factor (0-10 scale)
        
        Lower is better
        """
        overall_severity = contamination_risk.get('overall_severity', 'Low')
        
        # Convert severity to numeric score
        severity_scores = {
            'Low': 2.0,
            'Medium': 5.0,
            'High': 7.5,
            'Critical': 9.5
        }
        
        score = severity_scores.get(overall_severity, 5.0)
        
        # Get severity description
        if score <= 3:
            severity = "Low Risk"
        elif score <= 5:
            severity = "Moderate Risk"
        elif score <= 7:
            severity = "High Risk"
        else:
            severity = "Critical Risk"
        
        return {
            "score": score,
            "max_score": 10,
            "severity": severity
        }
    
    def _get_wqi_rating(self, score: float) -> str:
        """Get WQI rating based on score"""
        if score >= 90:
            return "Excellent"
        elif score >= 75:
            return "Good"
        elif score >= 50:
            return "Fair"
        elif score >= 25:
            return "Poor"
        else:
            return "Very Poor"
    
    def _find_parameter(self, parameters: Dict, search_name: str) -> str:
        """Find parameter key by name (case-insensitive)"""
        search_lower = search_name.lower()
        
        for key in parameters.keys():
            if search_lower in key.lower():
                return key
        
        return None
    
    def _get_default_wqi_config(self) -> Dict:
        """Default WQI configuration"""
        return {
            "scoring_type": "water_quality_index",
            "parameters": [
                "pH", "TDS", "Hardness", "Alkalinity", "Chloride",
                "Sulfate", "Nitrate", "Fluoride", "Iron", "Turbidity"
            ]
        }