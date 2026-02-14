"""
Scoring Service - Calculate total analysis score
100% Dynamic - Weights and scoring from database
"""

import logging
from typing import Dict, Any, List

from app.db.mongo import db
from app.models.schemas import TotalScore, ScoreComponent

logger = logging.getLogger(__name__)


class ScoringService:
    """Calculate total water quality analysis score"""
    
    async def calculate_total_score(
        self,
        chemical_composition: Dict,
        biological_indicators: Dict,
        compliance_checklist: Dict,
        contamination_risk: Dict
    ) -> Dict[str, Any]:
        """
        Calculate overall analysis score from all components
        
        Returns:
            {
                "overall_score": 85.0,
                "max_score": 100,
                "rating": "Good",
                "components": [...]
            }
        """
        try:
            logger.info("🎯 Calculating total analysis score")
            
            # Get scoring configuration from database
            config = await db.get_scoring_config("water_quality_index")
            if not config:
                config = self._get_default_config()
            
            weights = config.get('weights', {})
            
            # Calculate individual component scores
            components = []
            
            # 1. Chemical Parameters Score
            chem_score = self._calculate_chemical_score(chemical_composition)
            components.append({
                "name": "Chemical Parameters",
                "score": chem_score,
                "max_score": 100,
                "weight": weights.get('chemical_parameters', 0.40)
            })
            
            # 2. Biological Indicators Score
            bio_score = self._calculate_biological_score(biological_indicators)
            components.append({
                "name": "Biological Indicators",
                "score": bio_score,
                "max_score": 100,
                "weight": weights.get('biological_indicators', 0.30)
            })
            
            # 3. Compliance Score
            comp_score = compliance_checklist.get('overall_compliance', 0)
            components.append({
                "name": "Compliance",
                "score": comp_score,
                "max_score": 100,
                "weight": weights.get('compliance_score', 0.20)
            })
            
            # 4. Heavy Metals / Risk Score
            risk_score = self._calculate_risk_score(contamination_risk)
            components.append({
                "name": "Risk Assessment",
                "score": risk_score,
                "max_score": 100,
                "weight": weights.get('heavy_metals', 0.10)
            })
            
            # Calculate weighted overall score
            overall_score = sum(
                comp['score'] * comp['weight']
                for comp in components
            )
            
            # Get rating
            rating = self._get_rating(overall_score, config)
            
            logger.info(f"✅ Total score: {overall_score:.1f}/100 - {rating}")
            
            return {
                "overall_score": round(overall_score, 1),
                "max_score": 100,
                "rating": rating,
                "components": components
            }
            
        except Exception as e:
            logger.error(f"❌ Score calculation failed: {e}")
            raise Exception(f"Score calculation failed: {str(e)}")
    
    def _calculate_chemical_score(self, composition: Dict) -> float:
        """
        Calculate score from chemical composition
        
        Based on how many parameters are in optimal/good range
        """
        parameters = composition.get('parameters', [])
        
        if not parameters:
            return 50.0  # Default if no data
        
        status_scores = {
            'optimal': 100,
            'good': 80,
            'warning': 50,
            'critical': 20,
            'unknown': 60
        }
        
        total_score = 0
        for param in parameters:
            status = param.get('status', 'unknown')
            total_score += status_scores.get(status, 60)
        
        avg_score = total_score / len(parameters)
        
        return round(avg_score, 1)
    
    def _calculate_biological_score(self, indicators: Dict) -> float:
        """
        Calculate score from biological indicators
        
        Based on risk levels
        """
        indicator_list = indicators.get('indicators', [])
        
        if not indicator_list:
            return 80.0  # Default if no biological data
        
        risk_scores = {
            'Low': 100,
            'Medium': 60,
            'High': 30,
            'Critical': 10
        }
        
        total_score = 0
        for indicator in indicator_list:
            risk_level = indicator.get('risk_level', 'Low')
            total_score += risk_scores.get(risk_level, 60)
        
        avg_score = total_score / len(indicator_list)
        
        return round(avg_score, 1)
    
    def _calculate_risk_score(self, risk_data: Dict) -> float:
        """
        Calculate score from contamination risk
        
        Lower risk = higher score
        """
        overall_severity = risk_data.get('overall_severity', 'Low')
        
        severity_scores = {
            'Low': 100,
            'Medium': 70,
            'High': 40,
            'Critical': 10
        }
        
        return severity_scores.get(overall_severity, 70)
    
    def _get_rating(self, score: float, config: Dict) -> str:
        """
        Get text rating based on score
        
        Uses rating scale from database
        """
        rating_scale = config.get('rating_scale', [])
        
        if not rating_scale:
            rating_scale = [
                {"min": 90, "max": 100, "rating": "Excellent"},
                {"min": 75, "max": 90, "rating": "Good"},
                {"min": 50, "max": 75, "rating": "Fair"},
                {"min": 25, "max": 50, "rating": "Poor"},
                {"min": 0, "max": 25, "rating": "Very Poor"}
            ]
        
        for scale in rating_scale:
            if scale['min'] <= score <= scale['max']:
                return scale['rating']
        
        return "Unknown"
    
    def _get_default_config(self) -> Dict:
        """Default scoring configuration"""
        return {
            "scoring_type": "water_quality_index",
            "weights": {
                "chemical_parameters": 0.40,
                "biological_indicators": 0.30,
                "compliance_score": 0.20,
                "heavy_metals": 0.10
            },
            "rating_scale": [
                {"min": 90, "max": 100, "rating": "Excellent"},
                {"min": 75, "max": 90, "rating": "Good"},
                {"min": 50, "max": 75, "rating": "Fair"},
                {"min": 25, "max": 50, "rating": "Poor"},
                {"min": 0, "max": 25, "rating": "Very Poor"}
            ]
        }