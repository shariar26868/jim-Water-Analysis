"""
Compliance Service - Check regulatory compliance - COMPLETE FIXED VERSION
✅ Proper parameter name matching with normalization
✅ Multiple matching strategies (direct, normalized, fuzzy, aliases)
✅ Handles TDS, Sulfate/Sulphate, E.coli, etc.
✅ Better status determination
✅ WHO/Bangladesh standards support
"""

import logging
from typing import Dict, Any, List, Optional

from app.db.mongo import db

logger = logging.getLogger(__name__)


class ComplianceService:
    """Check water quality compliance against standards - COMPLETE FIXED VERSION"""
    
    # ✅ Parameter name aliases - comprehensive mapping
    PARAMETER_ALIASES = {
        # Physical parameters
        "tds": ["TDS", "Total Dissolved Solids", "Total_Dissolved_Solids", "Dissolved Solids"],
        "totaldissolvedsolids": ["TDS"],
        "turbidity": ["Turbidity", "Turb", "NTU"],
        "temperature": ["Temperature", "Temp"],
        "hardness": ["Hardness", "Total Hardness", "Total_Hardness"],
        
        # pH
        "ph": ["pH", "PH", "P.H"],
        
        # Ions
        "calcium": ["Calcium", "Ca"],
        "magnesium": ["Magnesium", "Mg"],
        "sodium": ["Sodium", "Na"],
        "potassium": ["Potassium", "K"],
        "chloride": ["Chloride", "Cl"],
        "sulfate": ["Sulfate", "Sulphate", "SO4"],
        "sulphate": ["Sulfate", "Sulphate", "SO4"],
        "bicarbonate": ["Bicarbonate", "HCO3", "Alkalinity", "Total Alkalinity", "Total_Alkalinity"],
        "totalalkalinity": ["Alkalinity", "Bicarbonate"],
        "alkalinity": ["Alkalinity", "Bicarbonate", "Total Alkalinity"],
        
        # Nutrients
        "nitrate": ["Nitrate", "NO3", "Nitrate-N"],
        "nitrite": ["Nitrite", "NO2", "Nitrite-N"],
        "phosphate": ["Phosphate", "PO4", "Phosphorus"],
        "ammonia": ["Ammonia", "NH3", "NH4", "Ammonium"],
        
        # Heavy metals
        "arsenic": ["Arsenic", "As"],
        "lead": ["Lead", "Pb"],
        "cadmium": ["Cadmium", "Cd"],
        "chromium": ["Chromium", "Cr"],
        "mercury": ["Mercury", "Hg"],
        "iron": ["Iron", "Fe"],
        "manganese": ["Manganese", "Mn"],
        "copper": ["Copper", "Cu"],
        "zinc": ["Zinc", "Zn"],
        "aluminum": ["Aluminum", "Aluminium", "Al"],
        
        # Microbiological
        "ecoli": ["E.coli", "E. coli", "E coli", "Escherichia coli"],
        "e.coli": ["E.coli", "Ecoli"],
        "e_coli": ["E.coli", "Ecoli"],
        "totalcoliform": ["Total Coliform", "Total_Coliform", "Coliform"],
        "total_coliform": ["Total Coliform", "Coliform"],
        "fecalcoliform": ["Fecal Coliform", "Fecal_Coliform", "Faecal Coliform"],
        
        # Disinfection
        "chlorine": ["Chlorine", "Free Chlorine", "Free_Chlorine", "Residual Chlorine"],
        "freechlorine": ["Chlorine", "Free Chlorine"],
        "free_chlorine": ["Chlorine", "Free Chlorine"],
        
        # Other chemicals
        "fluoride": ["Fluoride", "F"],
        "cyanide": ["Cyanide", "CN"],
    }
    
    async def check_compliance(
        self,
        parameters: Dict[str, Any],
        chemical_status: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """
        Check compliance against all standards - COMPLETE FIXED VERSION
        
        Args:
            parameters: Extracted water quality parameters
            chemical_status: Optional chemical status from composition analysis
            
        Returns:
            Compliance results with items, counts, and overall percentage
        """
        try:
            logger.info("✓ Checking compliance against standards")
            
            # Get compliance rules from database
            compliance_rules = await self._get_compliance_rules_from_db()
            
            if not compliance_rules:
                logger.warning("⚠️ No compliance rules found in database, using defaults")
                compliance_rules = self._get_default_rules()
            
            logger.info(f"📋 Checking against {len(compliance_rules)} compliance rules")
            
            items = []
            passed = 0
            failed = 0
            pending = 0
            
            # Track which parameters we've already checked to avoid duplicates
            checked_params = set()
            
            # Check each rule
            for rule in compliance_rules:
                param_name = rule.get('parameter')
                standard = rule.get('standard', 'WHO')
                
                # Skip if we've already checked this parameter for this standard
                check_key = f"{param_name}_{standard}"
                if check_key in checked_params:
                    continue
                checked_params.add(check_key)
                
                # ✅ FIXED: Enhanced parameter finding with multiple strategies
                param_key = self._find_parameter_multi_strategy(parameters, param_name)
                
                if not param_key:
                    # Parameter not tested
                    items.append({
                        "parameter": param_name,
                        "standard": standard,
                        "status": "Pending",
                        "actual_value": None,
                        "required_value": self._format_requirement(rule),
                        "unit": rule.get("unit", ""),
                        "remarks": "Not tested"
                    })
                    pending += 1
                    continue
                
                # Get actual value
                param_data = parameters[param_key]
                actual_value = param_data.get("value")
                actual_unit = param_data.get("unit", "")
                
                # ✅ Validate value
                if actual_value is None or not isinstance(actual_value, (int, float)):
                    items.append({
                        "parameter": param_name,
                        "standard": standard,
                        "status": "Pending",
                        "actual_value": None,
                        "required_value": self._format_requirement(rule),
                        "unit": rule.get("unit", ""),
                        "remarks": "Invalid or missing value"
                    })
                    pending += 1
                    continue
                
                # ✅ Check compliance against rule
                status, remarks = self._check_compliance_against_rule(actual_value, rule)
                
                # Update counts
                if status == "Passed":
                    passed += 1
                elif status == "Failed":
                    failed += 1
                else:
                    pending += 1
                
                items.append({
                    "parameter": param_name,
                    "standard": standard,
                    "status": status,
                    "actual_value": actual_value,
                    "required_value": self._format_requirement(rule),
                    "unit": rule.get("unit", actual_unit),
                    "remarks": remarks
                })
                
                logger.info(f"✓ {param_name}: {actual_value} → {status}")
            
            # Calculate overall compliance percentage
            total_tested = passed + failed
            if total_tested > 0:
                overall_compliance = (passed / total_tested) * 100
            else:
                overall_compliance = 0.0
            
            logger.info(f"✅ Compliance check complete - {passed} passed, {failed} failed, {pending} pending")
            
            return {
                "items": items,
                "overall_compliance": round(overall_compliance, 1),
                "passed_count": passed,
                "failed_count": failed,
                "pending_count": pending,
                "total_rules": len(compliance_rules)
            }
            
        except Exception as e:
            logger.error(f"❌ Compliance check failed: {e}")
            raise Exception(f"Compliance check failed: {str(e)}")
    
    async def _get_compliance_rules_from_db(self) -> List[Dict]:
        """Get compliance rules from MongoDB"""
        try:
            rules = await db.get_compliance_rules()
            return rules if rules else []
        except Exception as e:
            logger.error(f"Error fetching compliance rules: {e}")
            return []
    
    def _find_parameter_multi_strategy(
        self, 
        parameters: Dict, 
        search_name: str
    ) -> Optional[str]:
        """
        ✅ MULTI-STRATEGY parameter finding
        
        Tries multiple strategies in order:
        1. Direct exact match (case-insensitive)
        2. Normalized match (remove spaces, underscores, etc.)
        3. Alias match (using PARAMETER_ALIASES)
        4. Fuzzy contains match
        5. Partial word match
        
        Args:
            parameters: Dictionary of parameters
            search_name: Parameter name to search for
            
        Returns:
            Matching parameter key or None
        """
        if not parameters or not search_name:
            return None
        
        # Strategy 1: Direct exact match (case-insensitive)
        for key in parameters.keys():
            if key.lower() == search_name.lower():
                logger.debug(f"✓ Direct match: {search_name} → {key}")
                return key
        
        # Strategy 2: Normalized match (remove spaces, underscores, dashes)
        search_normalized = self._normalize_string(search_name)
        
        for key in parameters.keys():
            key_normalized = self._normalize_string(key)
            if search_normalized == key_normalized:
                logger.debug(f"✓ Normalized match: {search_name} → {key}")
                return key
        
        # Strategy 3: Alias match
        search_lower = search_name.lower()
        search_normalized_lower = search_normalized.lower()
        
        # Check if search term is in our aliases
        possible_matches = []
        
        if search_normalized_lower in self.PARAMETER_ALIASES:
            possible_matches = self.PARAMETER_ALIASES[search_normalized_lower]
        
        # Also check if any alias key matches the search
        for alias_key, alias_values in self.PARAMETER_ALIASES.items():
            if search_lower in alias_values or search_name in alias_values:
                possible_matches.extend(alias_values)
        
        # Check parameters against possible matches
        for key in parameters.keys():
            key_normalized = self._normalize_string(key)
            for match in possible_matches:
                match_normalized = self._normalize_string(match)
                if key_normalized.lower() == match_normalized.lower():
                    logger.debug(f"✓ Alias match: {search_name} → {key} (via {match})")
                    return key
        
        # Strategy 4: Fuzzy contains match
        for key in parameters.keys():
            key_lower = key.lower()
            if search_lower in key_lower or key_lower in search_lower:
                logger.debug(f"✓ Fuzzy match: {search_name} → {key}")
                return key
        
        # Strategy 5: Partial word match
        search_words = set(search_name.lower().replace("_", " ").replace("-", " ").split())
        
        for key in parameters.keys():
            key_words = set(key.lower().replace("_", " ").replace("-", " ").split())
            
            # If significant overlap in words
            common_words = search_words & key_words
            if common_words and len(common_words) >= min(len(search_words), len(key_words)) * 0.5:
                logger.debug(f"✓ Word match: {search_name} → {key} (common: {common_words})")
                return key
        
        # Not found
        logger.debug(f"✗ No match found for: {search_name}")
        return None
    
    def _normalize_string(self, s: str) -> str:
        """
        Normalize string for comparison
        
        Removes: spaces, underscores, dashes, dots
        Converts to lowercase
        """
        if not s:
            return ""
        
        normalized = s.lower()
        normalized = normalized.replace(" ", "")
        normalized = normalized.replace("_", "")
        normalized = normalized.replace("-", "")
        normalized = normalized.replace(".", "")
        
        return normalized
    
    def _check_compliance_against_rule(
        self, 
        actual_value: float, 
        rule: Dict
    ) -> tuple:
        """
        Check if value complies with rule
        
        Args:
            actual_value: The measured value
            rule: Compliance rule with min_value, max_value, etc.
            
        Returns:
            (status, remarks) where status is "Passed", "Failed", or "Pending"
        """
        if not isinstance(actual_value, (int, float)):
            return ("Pending", "Non-numeric value")
        
        min_val = rule.get('min_value')
        max_val = rule.get('max_value')
        
        # Range check (both min and max)
        if min_val is not None and max_val is not None:
            if min_val <= actual_value <= max_val:
                return ("Passed", f"Within range {min_val}-{max_val}")
            else:
                if actual_value < min_val:
                    return ("Failed", f"Below minimum ({min_val})")
                else:
                    return ("Failed", f"Exceeds maximum ({max_val})")
        
        # Only max check
        elif max_val is not None:
            if actual_value <= max_val:
                return ("Passed", f"Below maximum limit ({max_val})")
            else:
                return ("Failed", f"Exceeds maximum ({max_val})")
        
        # Only min check
        elif min_val is not None:
            if actual_value >= min_val:
                return ("Passed", f"Above minimum limit ({min_val})")
            else:
                return ("Failed", f"Below minimum ({min_val})")
        
        # No limits defined
        return ("Pending", "No requirement defined")
    
    def _format_requirement(self, rule: Dict) -> str:
        """
        Format requirement as readable string
        
        Examples:
            "6.5-8.5" (range)
            "≤ 10" (max only)
            "≥ 5" (min only)
        """
        min_val = rule.get('min_value')
        max_val = rule.get('max_value')
        
        if min_val is not None and max_val is not None:
            return f"{min_val}-{max_val}"
        elif max_val is not None:
            return f"≤ {max_val}"
        elif min_val is not None:
            return f"≥ {min_val}"
        else:
            return "Not specified"
    
    def _get_default_rules(self) -> List[Dict]:
        """
        Default compliance rules (WHO standards)
        
        Used as fallback if database has no rules
        """
        return [
            # Physical parameters
            {
                "parameter": "pH",
                "standard": "WHO",
                "min_value": 6.5,
                "max_value": 8.5,
                "unit": "",
                "severity": "high",
                "category": "physical"
            },
            {
                "parameter": "TDS",
                "standard": "WHO",
                "max_value": 500,
                "unit": "mg/L",
                "severity": "medium",
                "category": "physical"
            },
            {
                "parameter": "Turbidity",
                "standard": "WHO",
                "max_value": 5,
                "unit": "NTU",
                "severity": "medium",
                "category": "physical"
            },
            {
                "parameter": "Hardness",
                "standard": "WHO",
                "max_value": 500,
                "unit": "mg/L as CaCO3",
                "severity": "low",
                "category": "physical"
            },
            
            # Major ions
            {
                "parameter": "Chloride",
                "standard": "WHO",
                "max_value": 250,
                "unit": "mg/L",
                "severity": "low",
                "category": "anion"
            },
            {
                "parameter": "Sulfate",
                "standard": "WHO",
                "max_value": 250,
                "unit": "mg/L",
                "severity": "low",
                "category": "anion"
            },
            {
                "parameter": "Sodium",
                "standard": "WHO",
                "max_value": 200,
                "unit": "mg/L",
                "severity": "medium",
                "category": "cation"
            },
            {
                "parameter": "Calcium",
                "standard": "WHO",
                "min_value": 20,
                "max_value": 75,
                "unit": "mg/L",
                "severity": "low",
                "category": "cation"
            },
            {
                "parameter": "Magnesium",
                "standard": "WHO",
                "max_value": 50,
                "unit": "mg/L",
                "severity": "low",
                "category": "cation"
            },
            
            # Nutrients
            {
                "parameter": "Nitrate",
                "standard": "WHO",
                "max_value": 50,
                "unit": "mg/L",
                "severity": "high",
                "category": "nutrient"
            },
            {
                "parameter": "Nitrite",
                "standard": "WHO",
                "max_value": 3,
                "unit": "mg/L",
                "severity": "high",
                "category": "nutrient"
            },
            
            # Heavy metals
            {
                "parameter": "Arsenic",
                "standard": "WHO",
                "max_value": 0.01,
                "unit": "mg/L",
                "severity": "critical",
                "category": "heavy_metal"
            },
            {
                "parameter": "Lead",
                "standard": "WHO",
                "max_value": 0.01,
                "unit": "mg/L",
                "severity": "critical",
                "category": "heavy_metal"
            },
            {
                "parameter": "Cadmium",
                "standard": "WHO",
                "max_value": 0.003,
                "unit": "mg/L",
                "severity": "critical",
                "category": "heavy_metal"
            },
            {
                "parameter": "Chromium",
                "standard": "WHO",
                "max_value": 0.05,
                "unit": "mg/L",
                "severity": "high",
                "category": "heavy_metal"
            },
            {
                "parameter": "Mercury",
                "standard": "WHO",
                "max_value": 0.001,
                "unit": "mg/L",
                "severity": "critical",
                "category": "heavy_metal"
            },
            {
                "parameter": "Iron",
                "standard": "WHO",
                "max_value": 0.3,
                "unit": "mg/L",
                "severity": "low",
                "category": "metal"
            },
            {
                "parameter": "Manganese",
                "standard": "WHO",
                "max_value": 0.1,
                "unit": "mg/L",
                "severity": "low",
                "category": "metal"
            },
            
            # Other chemicals
            {
                "parameter": "Fluoride",
                "standard": "WHO",
                "max_value": 1.5,
                "unit": "mg/L",
                "severity": "high",
                "category": "chemical"
            },
            {
                "parameter": "Chlorine",
                "standard": "WHO",
                "min_value": 0.2,
                "max_value": 5.0,
                "unit": "mg/L",
                "severity": "medium",
                "category": "disinfectant"
            },
            
            # Microbiological
            {
                "parameter": "E.coli",
                "standard": "WHO",
                "max_value": 0,
                "unit": "CFU/100ml",
                "severity": "critical",
                "category": "microbiological"
            },
            {
                "parameter": "Total Coliform",
                "standard": "WHO",
                "max_value": 0,
                "unit": "CFU/100ml",
                "severity": "critical",
                "category": "microbiological"
            }
        ]