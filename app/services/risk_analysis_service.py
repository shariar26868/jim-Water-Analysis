

# """
# Risk Analysis Service - Contamination risk assessment - FIXED VERSION
# ✅ Fixed risk thresholds for Potassium, Nitrate
# ✅ Proper risk level assessment
# ✅ WHO/EPA standard compliance
# """

# import logging
# from typing import Dict, Any, List

# from app.db.mongo import db

# logger = logging.getLogger(__name__)


# # ✅ FIXED: Proper risk thresholds based on WHO/EPA standards
# PROPER_RISK_THRESHOLDS = {
#     # Heavy metals (mg/L) - very strict
#     "Lead": {"low": 0.001, "medium": 0.005, "high": 0.01, "critical": 0.05},
#     "Arsenic": {"low": 0.001, "medium": 0.005, "high": 0.01, "critical": 0.05},
#     "Mercury": {"low": 0.0001, "medium": 0.0005, "high": 0.001, "critical": 0.006},
#     "Cadmium": {"low": 0.001, "medium": 0.002, "high": 0.003, "critical": 0.01},
#     "Chromium": {"low": 0.01, "medium": 0.025, "high": 0.05, "critical": 0.1},
#     "Iron": {"low": 0.1, "medium": 0.2, "high": 0.3, "critical": 1.0},
#     "Manganese": {"low": 0.05, "medium": 0.1, "high": 0.2, "critical": 0.5},
    
#     # Nutrients (mg/L) - moderate thresholds
#     "Nitrate": {"low": 1.0, "medium": 10.0, "high": 25.0, "critical": 50.0},  # ✅ FIXED: WHO limit 50 mg/L
#     "Nitrite": {"low": 0.01, "medium": 0.5, "high": 1.0, "critical": 3.0},
#     "Phosphate": {"low": 0.1, "medium": 0.5, "high": 1.0, "critical": 5.0},
    
#     # Major ions (mg/L) - high thresholds
#     "Sodium": {"low": 20, "medium": 100, "high": 200, "critical": 400},  # ✅ FIXED: WHO ~200 mg/L
#     "Potassium": {"low": 2, "medium": 5, "high": 10, "critical": 12},  # ✅ FIXED: Normal 2-12 mg/L
#     "Chloride": {"low": 50, "medium": 150, "high": 250, "critical": 600},
#     "Sulfate": {"low": 50, "medium": 150, "high": 250, "critical": 500},
#     "Sulphate": {"low": 50, "medium": 150, "high": 250, "critical": 500},
    
#     # Organic (mg/L)
#     "Phenolic_Compounds": {"low": 0.001, "medium": 0.002, "high": 0.005, "critical": 0.01},
#     "BOD": {"low": 2, "medium": 5, "high": 10, "critical": 30},
#     "COD": {"low": 5, "medium": 10, "high": 20, "critical": 50},
    
#     # Microbiological (CFU/100mL)
#     "Total_Coliform": {"low": 0, "medium": 1, "high": 10, "critical": 50},
#     "E_coli": {"low": 0, "medium": 1, "high": 5, "critical": 10},
#     "Bacteria_Count": {"low": 0, "medium": 10, "high": 100, "critical": 500},
# }


# class RiskAnalysisService:
#     """Analyze contamination risks in water sample - FIXED VERSION"""
    
#     async def analyze_risks(
#         self,
#         parameters: Dict[str, Any],
#         chemical_status: Dict[str, Any]
#     ) -> Dict[str, Any]:
#         """
#         Comprehensive contamination risk analysis - FIXED
#         """
#         try:
#             logger.info("⚠️ Analyzing contamination risks")
            
#             # Analyze heavy metals
#             heavy_metals = await self._analyze_heavy_metals(parameters)
            
#             # Analyze organic compounds
#             organic_compounds = await self._analyze_organic_compounds(parameters)
            
#             # Analyze microbiological risks
#             microbiological = await self._analyze_microbiological(parameters)
            
#             # Calculate overall severity
#             overall_severity, risk_score = self._calculate_overall_severity(
#                 heavy_metals,
#                 organic_compounds,
#                 microbiological
#             )
            
#             logger.info(f"✅ Risk analysis complete - Overall: {overall_severity} (Score: {risk_score}/10)")
            
#             return {
#                 "heavy_metals": heavy_metals,
#                 "organic_compounds": organic_compounds,
#                 "microbiological": microbiological,
#                 "overall_severity": overall_severity,
#                 "risk_score": risk_score
#             }
            
#         except Exception as e:
#             logger.error(f"❌ Risk analysis failed: {e}")
#             raise Exception(f"Risk analysis failed: {str(e)}")
    
#     async def _analyze_heavy_metals(self, parameters: Dict) -> List[Dict]:
#         """Analyze heavy metal contamination - FIXED"""
#         heavy_metal_keywords = [
#             "lead", "arsenic", "mercury", "cadmium", "chromium",
#             "pb", "as", "hg", "cd", "cr", "copper", "cu", "zinc", "zn",
#             "nickel", "ni", "iron", "fe", "manganese", "mn"
#         ]
        
#         # ✅ EXCLUDE nutrients from heavy metals
#         exclude_keywords = ["nitrate", "nitrite", "phosphate", "potassium", "sodium"]
        
#         heavy_metals = []
        
#         for param_name, param_data in parameters.items():
#             param_lower = param_name.lower()
            
#             # Check if excluded
#             if any(ex in param_lower for ex in exclude_keywords):
#                 continue
            
#             # Check if it's a heavy metal
#             is_heavy_metal = any(keyword in param_lower for keyword in heavy_metal_keywords)
            
#             if not is_heavy_metal:
#                 continue
            
#             value = param_data.get("value")
#             unit = param_data.get("unit", "mg/L")
            
#             if not isinstance(value, (int, float)):
#                 continue
            
#             # Get standard
#             standard = await db.get_parameter_standard(param_name)
            
#             # ✅ Assess risk with FIXED thresholds
#             risk_level, threshold = self._assess_contaminant_risk_fixed(
#                 param_name,
#                 value,
#                 standard,
#                 contaminant_type="heavy_metal"
#             )
            
#             heavy_metals.append({
#                 "contaminant_name": param_name,
#                 "value": value,
#                 "unit": unit,
#                 "risk_level": risk_level,
#                 "threshold": threshold
#             })
            
#             logger.info(f"Heavy Metal: {param_name} = {value} {unit} → {risk_level}")
        
#         return heavy_metals
    
#     async def _analyze_organic_compounds(self, parameters: Dict) -> List[Dict]:
#         """Analyze organic compound contamination - FIXED"""
#         organic_keywords = [
#             "bod", "cod", "toc", "pesticide", "herbicide",
#             "voc", "benzene", "toluene", "phenol", "chloroform", "dioxin"
#         ]
        
#         organic_compounds = []
        
#         for param_name, param_data in parameters.items():
#             param_lower = param_name.lower()
            
#             # Check if it's organic
#             is_organic = any(keyword in param_lower for keyword in organic_keywords)
            
#             if not is_organic:
#                 continue
            
#             value = param_data.get("value")
#             unit = param_data.get("unit", "mg/L")
            
#             if not isinstance(value, (int, float)):
#                 continue
            
#             # Get standard
#             standard = await db.get_parameter_standard(param_name)
            
#             # ✅ Assess risk with FIXED thresholds
#             risk_level, threshold = self._assess_contaminant_risk_fixed(
#                 param_name,
#                 value,
#                 standard,
#                 contaminant_type="organic"
#             )
            
#             organic_compounds.append({
#                 "contaminant_name": param_name,
#                 "value": value,
#                 "unit": unit,
#                 "risk_level": risk_level,
#                 "threshold": threshold
#             })
            
#             logger.info(f"Organic: {param_name} = {value} {unit} → {risk_level}")
        
#         return organic_compounds
    
#     async def _analyze_microbiological(self, parameters: Dict) -> List[Dict]:
#         """Analyze microbiological contamination - FIXED"""
#         micro_keywords = [
#             "bacteria", "coliform", "e.coli", "e_coli", "pathogen",
#             "fecal", "total_plate", "cfu"
#         ]
        
#         microbiological = []
        
#         for param_name, param_data in parameters.items():
#             param_lower = param_name.lower()
            
#             # Check if it's microbiological
#             is_micro = any(keyword in param_lower for keyword in micro_keywords)
            
#             if not is_micro:
#                 continue
            
#             value = param_data.get("value")
#             unit = param_data.get("unit", "CFU/100mL")
            
#             if not isinstance(value, (int, float)):
#                 continue
            
#             # Get standard
#             standard = await db.get_parameter_standard(param_name)
            
#             # ✅ Assess risk with FIXED thresholds
#             risk_level, threshold = self._assess_contaminant_risk_fixed(
#                 param_name,
#                 value,
#                 standard,
#                 contaminant_type="microbiological"
#             )
            
#             microbiological.append({
#                 "contaminant_name": param_name,
#                 "value": value,
#                 "unit": unit,
#                 "risk_level": risk_level,
#                 "threshold": threshold
#             })
            
#             logger.info(f"Microbiological: {param_name} = {value} {unit} → {risk_level}")
        
#         return microbiological
    
#     def _assess_contaminant_risk_fixed(
#         self,
#         contaminant_name: str,
#         value: float,
#         standard: Dict,
#         contaminant_type: str
#     ) -> tuple:
#         """
#         ✅ FIXED: Assess risk level with proper thresholds
        
#         Returns: (risk_level, threshold)
#         """
#         # Try to find in PROPER_RISK_THRESHOLDS first
#         threshold_data = None
        
#         # Direct match
#         if contaminant_name in PROPER_RISK_THRESHOLDS:
#             threshold_data = PROPER_RISK_THRESHOLDS[contaminant_name]
#         else:
#             # Fuzzy match
#             name_lower = contaminant_name.lower().replace("_", "").replace(" ", "")
#             for key in PROPER_RISK_THRESHOLDS.keys():
#                 key_lower = key.lower().replace("_", "").replace(" ", "")
#                 if name_lower in key_lower or key_lower in name_lower:
#                     threshold_data = PROPER_RISK_THRESHOLDS[key]
#                     break
        
#         # If found proper thresholds, use them
#         if threshold_data:
#             low = threshold_data.get("low", 0.1)
#             medium = threshold_data.get("medium", 1.0)
#             high = threshold_data.get("high", 10.0)
#             critical = threshold_data.get("critical", 50.0)
            
#             if value <= low:
#                 return ("Low", low)
#             elif value <= medium:
#                 return ("Medium", medium)
#             elif value <= high:
#                 return ("High", high)
#             else:
#                 return ("Critical", critical)
        
#         # Fallback: use database standard
#         if standard:
#             thresholds = standard.get('thresholds', {})
            
#             optimal = thresholds.get('optimal', {}).get('max', 0.1)
#             good = thresholds.get('good', {}).get('max', 1.0)
#             warning = thresholds.get('warning', {}).get('max', 10.0)
#             critical = thresholds.get('critical', {}).get('max', 50.0)
            
#             if value <= optimal:
#                 return ("Low", optimal)
#             elif value <= good:
#                 return ("Medium", good)
#             elif value <= warning:
#                 return ("High", warning)
#             else:
#                 return ("Critical", critical)
        
#         # Last resort: generic defaults
#         return self._default_risk_assessment(contaminant_name, value, contaminant_type)
    
#     def _default_risk_assessment(
#         self,
#         contaminant_name: str,
#         value: float,
#         contaminant_type: str
#     ) -> tuple:
#         """Default risk assessment - FIXED"""
        
#         if contaminant_type == "heavy_metal":
#             if value < 0.01:
#                 return ("Low", 0.01)
#             elif value < 0.05:
#                 return ("Medium", 0.05)
#             elif value < 0.1:
#                 return ("High", 0.1)
#             else:
#                 return ("Critical", 0.1)
        
#         elif contaminant_type == "microbiological":
#             if value == 0:
#                 return ("Low", 0)
#             elif value < 10:
#                 return ("Medium", 10)
#             elif value < 100:
#                 return ("High", 100)
#             else:
#                 return ("Critical", 100)
        
#         else:  # organic
#             if value < 5:
#                 return ("Low", 5)
#             elif value < 20:
#                 return ("Medium", 20)
#             elif value < 50:
#                 return ("High", 50)
#             else:
#                 return ("Critical", 50)
    
#     def _calculate_overall_severity(
#         self,
#         heavy_metals: List[Dict],
#         organic_compounds: List[Dict],
#         microbiological: List[Dict]
#     ) -> tuple:
#         """
#         Calculate overall contamination severity
        
#         Returns: (severity_text, risk_score)
#         """
#         # Count risk levels
#         risk_counts = {
#             "Critical": 0,
#             "High": 0,
#             "Medium": 0,
#             "Low": 0
#         }
        
#         all_contaminants = heavy_metals + organic_compounds + microbiological
        
#         if not all_contaminants:
#             return ("Low", 1.0)
        
#         for contaminant in all_contaminants:
#             risk_level = contaminant.get("risk_level", "Low")
#             if risk_level in risk_counts:
#                 risk_counts[risk_level] += 1
        
#         # Calculate risk score (0-10)
#         total = sum(risk_counts.values())
#         if total == 0:
#             risk_score = 0.0
#         else:
#             weighted_score = (
#                 risk_counts["Critical"] * 10 +
#                 risk_counts["High"] * 7 +
#                 risk_counts["Medium"] * 4 +
#                 risk_counts["Low"] * 1
#             ) / total
#             risk_score = weighted_score
        
#         # Determine severity text
#         if risk_counts["Critical"] > 0:
#             severity = "Critical"
#         elif risk_counts["High"] > 0:
#             severity = "High"
#         elif risk_counts["Medium"] > 0:
#             severity = "Medium"
#         else:
#             severity = "Low"
        
#         return (severity, round(risk_score, 1))






"""
Risk Analysis Service - Contamination risk assessment - FIXED VERSION
✅ Fixed risk thresholds for all parameters
✅ Proper exclusion of non-contaminants (alkalinity, hardness, etc.)
✅ WHO/EPA standard compliance
✅ Clearer score naming to avoid confusion
✅ Enhanced logging
"""

import logging
from typing import Dict, Any, List

from app.db.mongo import db

logger = logging.getLogger(__name__)


# ✅ FIXED: Proper risk thresholds based on WHO/EPA standards
PROPER_RISK_THRESHOLDS = {
    # Heavy metals (mg/L) - very strict
    "Lead": {"low": 0.001, "medium": 0.005, "high": 0.01, "critical": 0.05},
    "Arsenic": {"low": 0.001, "medium": 0.005, "high": 0.01, "critical": 0.05},
    "Mercury": {"low": 0.0001, "medium": 0.0005, "high": 0.001, "critical": 0.006},
    "Cadmium": {"low": 0.001, "medium": 0.002, "high": 0.003, "critical": 0.01},
    "Chromium": {"low": 0.01, "medium": 0.025, "high": 0.05, "critical": 0.1},
    "Iron": {"low": 0.1, "medium": 0.2, "high": 0.3, "critical": 1.0},
    "Manganese": {"low": 0.05, "medium": 0.1, "high": 0.2, "critical": 0.5},
    "Copper": {"low": 0.05, "medium": 0.5, "high": 1.0, "critical": 2.0},
    "Zinc": {"low": 0.1, "medium": 1.0, "high": 3.0, "critical": 5.0},
    "Aluminum": {"low": 0.02, "medium": 0.1, "high": 0.2, "critical": 0.5},
    
    # Nutrients (mg/L) - moderate thresholds
    "Nitrate": {"low": 1.0, "medium": 10.0, "high": 25.0, "critical": 50.0},  # ✅ FIXED: WHO limit 50 mg/L
    "Nitrite": {"low": 0.01, "medium": 0.5, "high": 1.0, "critical": 3.0},
    "Phosphate": {"low": 0.1, "medium": 0.5, "high": 1.0, "critical": 5.0},
    "Ammonia": {"low": 0.05, "medium": 0.5, "high": 1.5, "critical": 5.0},
    
    # Major ions (mg/L) - high thresholds (these are NOT typically contaminants)
    "Sodium": {"low": 20, "medium": 100, "high": 200, "critical": 400},  # ✅ FIXED: WHO ~200 mg/L
    "Potassium": {"low": 2, "medium": 5, "high": 10, "critical": 12},  # ✅ FIXED: Normal 2-12 mg/L
    "Chloride": {"low": 50, "medium": 150, "high": 250, "critical": 600},
    "Sulfate": {"low": 50, "medium": 150, "high": 250, "critical": 500},
    "Sulphate": {"low": 50, "medium": 150, "high": 250, "critical": 500},
    
    # Organic (mg/L)
    "Phenolic_Compounds": {"low": 0.001, "medium": 0.002, "high": 0.005, "critical": 0.01},
    "BOD": {"low": 2, "medium": 5, "high": 10, "critical": 30},
    "COD": {"low": 5, "medium": 10, "high": 20, "critical": 50},
    "TOC": {"low": 1, "medium": 3, "high": 5, "critical": 10},
    
    # Microbiological (CFU/100mL)
    "Total_Coliform": {"low": 0, "medium": 1, "high": 10, "critical": 50},
    "E_coli": {"low": 0, "medium": 1, "high": 5, "critical": 10},
    "Fecal_Coliform": {"low": 0, "medium": 1, "high": 10, "critical": 50},
    "Bacteria_Count": {"low": 0, "medium": 10, "high": 100, "critical": 500},
}


class RiskAnalysisService:
    """Analyze contamination risks in water sample - FIXED VERSION"""
    
    async def analyze_risks(
        self,
        parameters: Dict[str, Any],
        chemical_status: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Comprehensive contamination risk analysis - FIXED
        """
        try:
            logger.info("⚠️ Analyzing contamination risks")
            
            # Analyze heavy metals
            heavy_metals = await self._analyze_heavy_metals(parameters)
            
            # Analyze organic compounds
            organic_compounds = await self._analyze_organic_compounds(parameters)
            
            # Analyze microbiological risks
            microbiological = await self._analyze_microbiological(parameters)
            
            # Calculate overall severity
            overall_severity, contamination_score = self._calculate_overall_severity(
                heavy_metals,
                organic_compounds,
                microbiological
            )
            
            # ✅ IMPROVED: Clearer naming and explanation
            logger.info(f"✅ Risk analysis complete - Overall: {overall_severity} (Contamination Score: {contamination_score}/10)")
            logger.info(f"ℹ️ Note: Contamination score: 0=safe, 10=critical (inverse of quality score)")
            
            return {
                "heavy_metals": heavy_metals,
                "organic_compounds": organic_compounds,
                "microbiological": microbiological,
                "overall_severity": overall_severity,
                "contamination_score": contamination_score,  # ✅ NEW: Clearer naming
                "risk_score": contamination_score,  # ✅ KEEP: Backward compatibility with Pydantic model
                "score_explanation": "contamination_score: 0=safe, 10=critical (inverse of water quality score)"
            }
            
        except Exception as e:
            logger.error(f"❌ Risk analysis failed: {e}")
            raise Exception(f"Risk analysis failed: {str(e)}")
    
    async def _analyze_heavy_metals(self, parameters: Dict) -> List[Dict]:
        """Analyze heavy metal contamination - FIXED"""
        heavy_metal_keywords = [
            "lead", "arsenic", "mercury", "cadmium", "chromium",
            "pb", "as", "hg", "cd", "cr", "copper", "cu", "zinc", "zn",
            "nickel", "ni", "iron", "fe", "manganese", "mn",
            "aluminum", "al", "barium", "ba"
        ]
        
        # ✅ FIXED: Comprehensive exclusion list - these are NOT contaminants
        exclude_keywords = [
            # Nutrients
            "nitrate", "nitrite", "phosphate", "ammonia", "nitrogen",
            
            # Major ions (normal water constituents)
            "potassium", "sodium", "calcium", "magnesium", "chloride", "sulfate", "sulphate",
            
            # ✅ CRITICAL FIX: Alkalinity and related
            "alkalinity", "bicarbonate", "carbonate", "hardness",
            
            # Physical parameters
            "tds", "conductivity", "temperature", "ph", "turbidity", "color",
            
            # Disinfection
            "chlorine", "free_chlorine", "total_chlorine", "residual_chlorine"
        ]
        
        heavy_metals = []
        
        for param_name, param_data in parameters.items():
            param_lower = param_name.lower()
            
            # ✅ FIXED: Check exclusions first
            if any(ex in param_lower for ex in exclude_keywords):
                logger.debug(f"Excluded from heavy metals: {param_name}")
                continue
            
            # Check if it's a heavy metal
            is_heavy_metal = any(keyword in param_lower for keyword in heavy_metal_keywords)
            
            if not is_heavy_metal:
                continue
            
            value = param_data.get("value")
            unit = param_data.get("unit", "mg/L")
            
            if not isinstance(value, (int, float)):
                continue
            
            # Get standard
            standard = await db.get_parameter_standard(param_name)
            
            # ✅ Assess risk with FIXED thresholds
            risk_level, threshold = self._assess_contaminant_risk_fixed(
                param_name,
                value,
                standard,
                contaminant_type="heavy_metal"
            )
            
            heavy_metals.append({
                "contaminant_name": param_name,
                "value": value,
                "unit": unit,
                "risk_level": risk_level,
                "threshold": threshold
            })
            
            logger.info(f"Heavy Metal: {param_name} = {value} {unit} → {risk_level}")
        
        return heavy_metals
    
    async def _analyze_organic_compounds(self, parameters: Dict) -> List[Dict]:
        """Analyze organic compound contamination - FIXED"""
        organic_keywords = [
            "bod", "cod", "toc", "doc", "pesticide", "herbicide",
            "voc", "benzene", "toluene", "phenol", "chloroform", "dioxin",
            "thm", "trihalomethane", "petroleum", "oil", "grease",
            "detergent", "surfactant"
        ]
        
        # ✅ FIXED: Exclude inorganic parameters
        exclude_keywords = [
            "ph", "alkalinity", "hardness", "tds", "conductivity",
            "chloride", "sulfate", "nitrate", "phosphate"
        ]
        
        organic_compounds = []
        
        for param_name, param_data in parameters.items():
            param_lower = param_name.lower()
            
            # Check exclusions
            if any(ex in param_lower for ex in exclude_keywords):
                continue
            
            # Check if it's organic
            is_organic = any(keyword in param_lower for keyword in organic_keywords)
            
            if not is_organic:
                continue
            
            value = param_data.get("value")
            unit = param_data.get("unit", "mg/L")
            
            if not isinstance(value, (int, float)):
                continue
            
            # Get standard
            standard = await db.get_parameter_standard(param_name)
            
            # ✅ Assess risk with FIXED thresholds
            risk_level, threshold = self._assess_contaminant_risk_fixed(
                param_name,
                value,
                standard,
                contaminant_type="organic"
            )
            
            organic_compounds.append({
                "contaminant_name": param_name,
                "value": value,
                "unit": unit,
                "risk_level": risk_level,
                "threshold": threshold
            })
            
            logger.info(f"Organic: {param_name} = {value} {unit} → {risk_level}")
        
        return organic_compounds
    
    async def _analyze_microbiological(self, parameters: Dict) -> List[Dict]:
        """Analyze microbiological contamination - FIXED"""
        micro_keywords = [
            "bacteria", "coliform", "e.coli", "e_coli", "pathogen",
            "fecal", "total_plate", "cfu", "enterococc", "coliforms"
        ]
        
        # ✅ Exclude chemical parameters
        exclude_keywords = [
            "ph", "alkalinity", "chlorine", "chloride"
        ]
        
        microbiological = []
        
        for param_name, param_data in parameters.items():
            param_lower = param_name.lower()
            
            # Check exclusions
            if any(ex in param_lower for ex in exclude_keywords):
                continue
            
            # Check if it's microbiological
            is_micro = any(keyword in param_lower for keyword in micro_keywords)
            
            if not is_micro:
                continue
            
            value = param_data.get("value")
            unit = param_data.get("unit", "CFU/100mL")
            
            if not isinstance(value, (int, float)):
                continue
            
            # Get standard
            standard = await db.get_parameter_standard(param_name)
            
            # ✅ Assess risk with FIXED thresholds
            risk_level, threshold = self._assess_contaminant_risk_fixed(
                param_name,
                value,
                standard,
                contaminant_type="microbiological"
            )
            
            microbiological.append({
                "contaminant_name": param_name,
                "value": value,
                "unit": unit,
                "risk_level": risk_level,
                "threshold": threshold
            })
            
            logger.info(f"Microbiological: {param_name} = {value} {unit} → {risk_level}")
        
        return microbiological
    
    def _assess_contaminant_risk_fixed(
        self,
        contaminant_name: str,
        value: float,
        standard: Dict,
        contaminant_type: str
    ) -> tuple:
        """
        ✅ FIXED: Assess risk level with proper thresholds
        
        Returns: (risk_level, threshold)
        """
        # Try to find in PROPER_RISK_THRESHOLDS first
        threshold_data = None
        
        # Direct match
        if contaminant_name in PROPER_RISK_THRESHOLDS:
            threshold_data = PROPER_RISK_THRESHOLDS[contaminant_name]
        else:
            # Fuzzy match
            name_lower = contaminant_name.lower().replace("_", "").replace(" ", "")
            for key in PROPER_RISK_THRESHOLDS.keys():
                key_lower = key.lower().replace("_", "").replace(" ", "")
                if name_lower in key_lower or key_lower in name_lower:
                    threshold_data = PROPER_RISK_THRESHOLDS[key]
                    logger.debug(f"Matched {contaminant_name} to threshold {key}")
                    break
        
        # If found proper thresholds, use them
        if threshold_data:
            low = threshold_data.get("low", 0.1)
            medium = threshold_data.get("medium", 1.0)
            high = threshold_data.get("high", 10.0)
            critical = threshold_data.get("critical", 50.0)
            
            if value <= low:
                return ("Low", low)
            elif value <= medium:
                return ("Medium", medium)
            elif value <= high:
                return ("High", high)
            else:
                return ("Critical", critical)
        
        # Fallback: use database standard
        if standard:
            thresholds = standard.get('thresholds', {})
            
            optimal = thresholds.get('optimal', {}).get('max', 0.1)
            good = thresholds.get('good', {}).get('max', 1.0)
            warning = thresholds.get('warning', {}).get('max', 10.0)
            critical = thresholds.get('critical', {}).get('max', 50.0)
            
            if value <= optimal:
                return ("Low", optimal)
            elif value <= good:
                return ("Medium", good)
            elif value <= warning:
                return ("High", warning)
            else:
                return ("Critical", critical)
        
        # Last resort: generic defaults based on contaminant type
        return self._default_risk_assessment(contaminant_name, value, contaminant_type)
    
    def _default_risk_assessment(
        self,
        contaminant_name: str,
        value: float,
        contaminant_type: str
    ) -> tuple:
        """Default risk assessment based on contaminant type - FIXED"""
        
        if contaminant_type == "heavy_metal":
            # Very strict for heavy metals
            if value < 0.01:
                return ("Low", 0.01)
            elif value < 0.05:
                return ("Medium", 0.05)
            elif value < 0.1:
                return ("High", 0.1)
            else:
                return ("Critical", 0.1)
        
        elif contaminant_type == "microbiological":
            # Zero tolerance for pathogens
            if value == 0:
                return ("Low", 0)
            elif value < 10:
                return ("Medium", 10)
            elif value < 100:
                return ("High", 100)
            else:
                return ("Critical", 100)
        
        else:  # organic
            # Moderate thresholds for organics
            if value < 5:
                return ("Low", 5)
            elif value < 20:
                return ("Medium", 20)
            elif value < 50:
                return ("High", 50)
            else:
                return ("Critical", 50)
    
    def _calculate_overall_severity(
        self,
        heavy_metals: List[Dict],
        organic_compounds: List[Dict],
        microbiological: List[Dict]
    ) -> tuple:
        """
        Calculate overall contamination severity - FIXED
        
        Returns: (severity_text, contamination_score)
        
        ✅ IMPROVED: Better naming and explanation
        contamination_score: 0 (safe) to 10 (critical)
        This is INVERSE of water quality score (quality: 100=good, 0=bad)
        """
        # Count risk levels
        risk_counts = {
            "Critical": 0,
            "High": 0,
            "Medium": 0,
            "Low": 0
        }
        
        all_contaminants = heavy_metals + organic_compounds + microbiological
        
        if not all_contaminants:
            logger.info("✅ No contaminants detected")
            return ("Low", 1.0)
        
        for contaminant in all_contaminants:
            risk_level = contaminant.get("risk_level", "Low")
            if risk_level in risk_counts:
                risk_counts[risk_level] += 1
        
        # Calculate contamination score (0-10, higher is worse)
        total = sum(risk_counts.values())
        if total == 0:
            contamination_score = 0.0
        else:
            weighted_score = (
                risk_counts["Critical"] * 10 +
                risk_counts["High"] * 7 +
                risk_counts["Medium"] * 4 +
                risk_counts["Low"] * 1
            ) / total
            contamination_score = weighted_score
        
        # Determine severity text
        if risk_counts["Critical"] > 0:
            severity = "Critical"
        elif risk_counts["High"] > 0:
            severity = "High"
        elif risk_counts["Medium"] > 0:
            severity = "Medium"
        else:
            severity = "Low"
        
        # ✅ IMPROVED: Log breakdown
        logger.info(f"📊 Risk breakdown: Critical={risk_counts['Critical']}, "
                   f"High={risk_counts['High']}, Medium={risk_counts['Medium']}, "
                   f"Low={risk_counts['Low']}")
        
        return (severity, round(contamination_score, 1))