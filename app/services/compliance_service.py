"""
Compliance Service - Potable Water Compliance Assessment
✅ Location-based standards (US: NSF 60/EPA, EU: DWD, AU: ADWG, WHO: default)
✅ AI-assisted local standard lookup via location string
✅ Proper parameter name matching with normalization
✅ Multiple matching strategies (direct, normalized, fuzzy, aliases)
"""

import logging
from typing import Dict, Any, List, Optional

from app.db.mongo import db

logger = logging.getLogger(__name__)

# ── Location → Standard mapping ──────────────────────────────────────────────
LOCATION_STANDARD_MAP = {
    # United States
    "us": "EPA/NSF60",
    "usa": "EPA/NSF60",
    "united states": "EPA/NSF60",
    # European Union
    "eu": "EU-DWD",
    "europe": "EU-DWD",
    "uk": "EU-DWD",
    "united kingdom": "EU-DWD",
    # Australia
    "au": "ADWG",
    "australia": "ADWG",
    # Canada
    "ca": "Health Canada",
    "canada": "Health Canada",
    # Bangladesh
    "bd": "Bangladesh-ECR",
    "bangladesh": "Bangladesh-ECR",
    # India
    "in": "BIS-10500",
    "india": "BIS-10500",
}

# ── Standards data ────────────────────────────────────────────────────────────
# Each standard defines max limits (mg/L unless noted)
STANDARDS: Dict[str, List[Dict]] = {

    "WHO": [
        {"parameter": "pH",            "min_value": 6.5,   "max_value": 8.5,    "unit": "",          "category": "physical",        "severity": "high"},
        {"parameter": "TDS",           "max_value": 500,                         "unit": "mg/L",      "category": "physical",        "severity": "medium"},
        {"parameter": "Turbidity",     "max_value": 5,                           "unit": "NTU",       "category": "physical",        "severity": "medium"},
        {"parameter": "Hardness",      "max_value": 500,                         "unit": "mg/L",      "category": "physical",        "severity": "low"},
        {"parameter": "Chloride",      "max_value": 250,                         "unit": "mg/L",      "category": "anion",           "severity": "low"},
        {"parameter": "Sulfate",       "max_value": 250,                         "unit": "mg/L",      "category": "anion",           "severity": "low"},
        {"parameter": "Sodium",        "max_value": 200,                         "unit": "mg/L",      "category": "cation",          "severity": "medium"},
        {"parameter": "Nitrate",       "max_value": 50,                          "unit": "mg/L",      "category": "nutrient",        "severity": "high"},
        {"parameter": "Nitrite",       "max_value": 3,                           "unit": "mg/L",      "category": "nutrient",        "severity": "high"},
        {"parameter": "Fluoride",      "max_value": 1.5,                         "unit": "mg/L",      "category": "chemical",        "severity": "high"},
        {"parameter": "Arsenic",       "max_value": 0.01,                        "unit": "mg/L",      "category": "heavy_metal",     "severity": "critical"},
        {"parameter": "Lead",          "max_value": 0.01,                        "unit": "mg/L",      "category": "heavy_metal",     "severity": "critical"},
        {"parameter": "Cadmium",       "max_value": 0.003,                       "unit": "mg/L",      "category": "heavy_metal",     "severity": "critical"},
        {"parameter": "Chromium",      "max_value": 0.05,                        "unit": "mg/L",      "category": "heavy_metal",     "severity": "high"},
        {"parameter": "Mercury",       "max_value": 0.001,                       "unit": "mg/L",      "category": "heavy_metal",     "severity": "critical"},
        {"parameter": "Iron",          "max_value": 0.3,                         "unit": "mg/L",      "category": "metal",           "severity": "low"},
        {"parameter": "Manganese",     "max_value": 0.1,                         "unit": "mg/L",      "category": "metal",           "severity": "low"},
        {"parameter": "E.coli",        "max_value": 0,                           "unit": "CFU/100mL", "category": "microbiological", "severity": "critical"},
        {"parameter": "Total Coliform","max_value": 0,                           "unit": "CFU/100mL", "category": "microbiological", "severity": "critical"},
    ],

    "EPA/NSF60": [
        # EPA Primary Standards (health-based)
        {"parameter": "pH",            "min_value": 6.5,   "max_value": 8.5,    "unit": "",          "category": "physical",        "severity": "high",     "reference": "EPA Secondary"},
        {"parameter": "TDS",           "max_value": 500,                         "unit": "mg/L",      "category": "physical",        "severity": "medium",   "reference": "EPA Secondary"},
        {"parameter": "Turbidity",     "max_value": 1,                           "unit": "NTU",       "category": "physical",        "severity": "high",     "reference": "EPA Primary"},
        {"parameter": "Chloride",      "max_value": 250,                         "unit": "mg/L",      "category": "anion",           "severity": "low",      "reference": "EPA Secondary"},
        {"parameter": "Sulfate",       "max_value": 250,                         "unit": "mg/L",      "category": "anion",           "severity": "low",      "reference": "EPA Secondary"},
        {"parameter": "Sodium",        "max_value": 160,                         "unit": "mg/L",      "category": "cation",          "severity": "medium",   "reference": "EPA Advisory"},
        {"parameter": "Nitrate",       "max_value": 10,                          "unit": "mg/L as N", "category": "nutrient",        "severity": "critical", "reference": "EPA Primary MCL"},
        {"parameter": "Nitrite",       "max_value": 1,                           "unit": "mg/L as N", "category": "nutrient",        "severity": "critical", "reference": "EPA Primary MCL"},
        {"parameter": "Fluoride",      "max_value": 4.0,                         "unit": "mg/L",      "category": "chemical",        "severity": "high",     "reference": "EPA Primary MCL"},
        {"parameter": "Arsenic",       "max_value": 0.01,                        "unit": "mg/L",      "category": "heavy_metal",     "severity": "critical", "reference": "EPA Primary MCL"},
        {"parameter": "Lead",          "max_value": 0.015,                       "unit": "mg/L",      "category": "heavy_metal",     "severity": "critical", "reference": "EPA Action Level"},
        {"parameter": "Copper",        "max_value": 1.3,                         "unit": "mg/L",      "category": "heavy_metal",     "severity": "high",     "reference": "EPA Action Level"},
        {"parameter": "Cadmium",       "max_value": 0.005,                       "unit": "mg/L",      "category": "heavy_metal",     "severity": "critical", "reference": "EPA Primary MCL"},
        {"parameter": "Chromium",      "max_value": 0.1,                         "unit": "mg/L",      "category": "heavy_metal",     "severity": "high",     "reference": "EPA Primary MCL"},
        {"parameter": "Mercury",       "max_value": 0.002,                       "unit": "mg/L",      "category": "heavy_metal",     "severity": "critical", "reference": "EPA Primary MCL"},
        {"parameter": "Barium",        "max_value": 2.0,                         "unit": "mg/L",      "category": "heavy_metal",     "severity": "high",     "reference": "EPA Primary MCL"},
        {"parameter": "Iron",          "max_value": 0.3,                         "unit": "mg/L",      "category": "metal",           "severity": "low",      "reference": "EPA Secondary"},
        {"parameter": "Manganese",     "max_value": 0.05,                        "unit": "mg/L",      "category": "metal",           "severity": "low",      "reference": "EPA Secondary"},
        {"parameter": "Zinc",          "max_value": 5.0,                         "unit": "mg/L",      "category": "metal",           "severity": "low",      "reference": "EPA Secondary"},
        {"parameter": "E.coli",        "max_value": 0,                           "unit": "CFU/100mL", "category": "microbiological", "severity": "critical", "reference": "EPA Primary MCL"},
        {"parameter": "Total Coliform","max_value": 0,                           "unit": "CFU/100mL", "category": "microbiological", "severity": "critical", "reference": "EPA Primary MCL"},
        # NSF 60 specific
        {"parameter": "Chlorine",      "min_value": 0.2,   "max_value": 4.0,    "unit": "mg/L",      "category": "disinfectant",    "severity": "medium",   "reference": "NSF 60 / EPA"},
    ],

    "EU-DWD": [
        # EU Drinking Water Directive 2020/2184
        {"parameter": "pH",            "min_value": 6.5,   "max_value": 9.5,    "unit": "",          "category": "physical",        "severity": "high",     "reference": "EU DWD 2020"},
        {"parameter": "TDS",           "max_value": 2500,                        "unit": "mg/L",      "category": "physical",        "severity": "low",      "reference": "EU DWD 2020"},
        {"parameter": "Turbidity",     "max_value": 4,                           "unit": "NTU",       "category": "physical",        "severity": "medium",   "reference": "EU DWD 2020"},
        {"parameter": "Chloride",      "max_value": 250,                         "unit": "mg/L",      "category": "anion",           "severity": "low",      "reference": "EU DWD 2020"},
        {"parameter": "Sulfate",       "max_value": 250,                         "unit": "mg/L",      "category": "anion",           "severity": "low",      "reference": "EU DWD 2020"},
        {"parameter": "Sodium",        "max_value": 200,                         "unit": "mg/L",      "category": "cation",          "severity": "medium",   "reference": "EU DWD 2020"},
        {"parameter": "Nitrate",       "max_value": 50,                          "unit": "mg/L",      "category": "nutrient",        "severity": "high",     "reference": "EU DWD 2020"},
        {"parameter": "Nitrite",       "max_value": 0.5,                         "unit": "mg/L",      "category": "nutrient",        "severity": "high",     "reference": "EU DWD 2020"},
        {"parameter": "Fluoride",      "max_value": 1.5,                         "unit": "mg/L",      "category": "chemical",        "severity": "high",     "reference": "EU DWD 2020"},
        {"parameter": "Arsenic",       "max_value": 0.01,                        "unit": "mg/L",      "category": "heavy_metal",     "severity": "critical", "reference": "EU DWD 2020"},
        {"parameter": "Lead",          "max_value": 0.005,                       "unit": "mg/L",      "category": "heavy_metal",     "severity": "critical", "reference": "EU DWD 2020"},
        {"parameter": "Cadmium",       "max_value": 0.005,                       "unit": "mg/L",      "category": "heavy_metal",     "severity": "critical", "reference": "EU DWD 2020"},
        {"parameter": "Chromium",      "max_value": 0.025,                       "unit": "mg/L",      "category": "heavy_metal",     "severity": "high",     "reference": "EU DWD 2020"},
        {"parameter": "Mercury",       "max_value": 0.001,                       "unit": "mg/L",      "category": "heavy_metal",     "severity": "critical", "reference": "EU DWD 2020"},
        {"parameter": "Copper",        "max_value": 2.0,                         "unit": "mg/L",      "category": "heavy_metal",     "severity": "high",     "reference": "EU DWD 2020"},
        {"parameter": "Iron",          "max_value": 0.2,                         "unit": "mg/L",      "category": "metal",           "severity": "low",      "reference": "EU DWD 2020"},
        {"parameter": "Manganese",     "max_value": 0.05,                        "unit": "mg/L",      "category": "metal",           "severity": "low",      "reference": "EU DWD 2020"},
        {"parameter": "E.coli",        "max_value": 0,                           "unit": "CFU/100mL", "category": "microbiological", "severity": "critical", "reference": "EU DWD 2020"},
        {"parameter": "Total Coliform","max_value": 0,                           "unit": "CFU/100mL", "category": "microbiological", "severity": "critical", "reference": "EU DWD 2020"},
    ],

    "ADWG": [
        # Australian Drinking Water Guidelines
        {"parameter": "pH",            "min_value": 6.5,   "max_value": 8.5,    "unit": "",          "category": "physical",        "severity": "high",     "reference": "ADWG 2011"},
        {"parameter": "TDS",           "max_value": 500,                         "unit": "mg/L",      "category": "physical",        "severity": "medium",   "reference": "ADWG 2011"},
        {"parameter": "Turbidity",     "max_value": 5,                           "unit": "NTU",       "category": "physical",        "severity": "medium",   "reference": "ADWG 2011"},
        {"parameter": "Chloride",      "max_value": 250,                         "unit": "mg/L",      "category": "anion",           "severity": "low",      "reference": "ADWG 2011"},
        {"parameter": "Sulfate",       "max_value": 250,                         "unit": "mg/L",      "category": "anion",           "severity": "low",      "reference": "ADWG 2011"},
        {"parameter": "Nitrate",       "max_value": 50,                          "unit": "mg/L",      "category": "nutrient",        "severity": "high",     "reference": "ADWG 2011"},
        {"parameter": "Fluoride",      "max_value": 1.5,                         "unit": "mg/L",      "category": "chemical",        "severity": "high",     "reference": "ADWG 2011"},
        {"parameter": "Arsenic",       "max_value": 0.01,                        "unit": "mg/L",      "category": "heavy_metal",     "severity": "critical", "reference": "ADWG 2011"},
        {"parameter": "Lead",          "max_value": 0.01,                        "unit": "mg/L",      "category": "heavy_metal",     "severity": "critical", "reference": "ADWG 2011"},
        {"parameter": "Mercury",       "max_value": 0.001,                       "unit": "mg/L",      "category": "heavy_metal",     "severity": "critical", "reference": "ADWG 2011"},
        {"parameter": "E.coli",        "max_value": 0,                           "unit": "CFU/100mL", "category": "microbiological", "severity": "critical", "reference": "ADWG 2011"},
    ],

    "Health Canada": [
        {"parameter": "pH",            "min_value": 7.0,   "max_value": 10.5,   "unit": "",          "category": "physical",        "severity": "high",     "reference": "GCDWQ"},
        {"parameter": "TDS",           "max_value": 500,                         "unit": "mg/L",      "category": "physical",        "severity": "medium",   "reference": "GCDWQ"},
        {"parameter": "Turbidity",     "max_value": 1,                           "unit": "NTU",       "category": "physical",        "severity": "high",     "reference": "GCDWQ"},
        {"parameter": "Nitrate",       "max_value": 45,                          "unit": "mg/L",      "category": "nutrient",        "severity": "high",     "reference": "GCDWQ"},
        {"parameter": "Fluoride",      "max_value": 1.5,                         "unit": "mg/L",      "category": "chemical",        "severity": "high",     "reference": "GCDWQ"},
        {"parameter": "Arsenic",       "max_value": 0.01,                        "unit": "mg/L",      "category": "heavy_metal",     "severity": "critical", "reference": "GCDWQ"},
        {"parameter": "Lead",          "max_value": 0.005,                       "unit": "mg/L",      "category": "heavy_metal",     "severity": "critical", "reference": "GCDWQ"},
        {"parameter": "E.coli",        "max_value": 0,                           "unit": "CFU/100mL", "category": "microbiological", "severity": "critical", "reference": "GCDWQ"},
    ],
}


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
        chemical_status: Dict[str, Any] = None,
        location: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Potable Water Compliance Assessment — location-aware.

        Args:
            parameters:      Extracted water quality parameters
            chemical_status: Optional PHREEQC chemical status
            location:        Country/region string e.g. "US", "EU", "AU", "WHO"

        Returns:
            Compliance results with standard name, items, counts, overall %
        """
        try:
            # Resolve standard from location
            standard_name = self._resolve_standard(location)
            logger.info(f"✓ Potable Water Compliance — standard: {standard_name} (location: {location or 'not specified'})")

            # Try DB first, fall back to built-in STANDARDS dict
            compliance_rules = await self._get_compliance_rules_from_db(standard_name)
            if not compliance_rules:
                compliance_rules = STANDARDS.get(standard_name, STANDARDS["WHO"])
                logger.info(f"Using built-in {standard_name} rules ({len(compliance_rules)} rules)")

            items = []
            passed = failed = pending = 0
            checked_params: set = set()

            for rule in compliance_rules:
                param_name = rule.get("parameter")
                check_key  = f"{param_name}_{standard_name}"
                if check_key in checked_params:
                    continue
                checked_params.add(check_key)

                param_key = self._find_parameter_multi_strategy(parameters, param_name)

                if not param_key:
                    items.append({
                        "parameter":      param_name,
                        "standard":       standard_name,
                        "reference":      rule.get("reference", standard_name),
                        "status":         "Pending",
                        "actual_value":   None,
                        "required_value": self._format_requirement(rule),
                        "unit":           rule.get("unit", ""),
                        "category":       rule.get("category", ""),
                        "severity":       rule.get("severity", ""),
                        "remarks":        "Not tested",
                    })
                    pending += 1
                    continue

                param_data   = parameters[param_key]
                actual_value = param_data.get("value")

                if actual_value is None or not isinstance(actual_value, (int, float)):
                    items.append({
                        "parameter":      param_name,
                        "standard":       standard_name,
                        "reference":      rule.get("reference", standard_name),
                        "status":         "Pending",
                        "actual_value":   None,
                        "required_value": self._format_requirement(rule),
                        "unit":           rule.get("unit", ""),
                        "category":       rule.get("category", ""),
                        "severity":       rule.get("severity", ""),
                        "remarks":        "Invalid or missing value",
                    })
                    pending += 1
                    continue

                status, remarks = self._check_compliance_against_rule(actual_value, rule)
                if status == "Passed":   passed  += 1
                elif status == "Failed": failed  += 1
                else:                   pending += 1

                items.append({
                    "parameter":      param_name,
                    "standard":       standard_name,
                    "reference":      rule.get("reference", standard_name),
                    "status":         status,
                    "actual_value":   actual_value,
                    "required_value": self._format_requirement(rule),
                    "unit":           rule.get("unit", param_data.get("unit", "")),
                    "category":       rule.get("category", ""),
                    "severity":       rule.get("severity", ""),
                    "remarks":        remarks,
                })
                logger.info(f"✓ {param_name}: {actual_value} → {status}")

            total_tested     = passed + failed
            overall_pct      = round((passed / total_tested) * 100, 1) if total_tested else 0.0

            logger.info(f"✅ Compliance complete — {passed} passed, {failed} failed, {pending} pending")

            return {
                "assessment_title": "Potable Water Compliance Assessment",
                "standard_applied": standard_name,
                "location":         location or "Not specified",
                "items":            items,
                "overall_compliance": overall_pct,
                "passed_count":     passed,
                "failed_count":     failed,
                "pending_count":    pending,
                "total_rules":      len(compliance_rules),
            }

        except Exception as e:
            logger.error(f"❌ Compliance check failed: {e}")
            raise Exception(f"Compliance check failed: {str(e)}")
    
    async def _get_compliance_rules_from_db(self, standard_name: str = "WHO") -> List[Dict]:
        """Get compliance rules from MongoDB for a specific standard"""
        try:
            rules = await db.get_compliance_rules()
            if rules:
                # Filter by standard if DB has standard-specific rules
                filtered = [r for r in rules if r.get("standard", "WHO") == standard_name]
                return filtered if filtered else rules
            return []
        except Exception as e:
            logger.error(f"Error fetching compliance rules: {e}")
            return []

    def _resolve_standard(self, location: Optional[str]) -> str:
        """Map location string → standard name."""
        if not location:
            return "WHO"
        key = location.strip().lower()
        return LOCATION_STANDARD_MAP.get(key, "WHO")
    
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
    