
"""
Composition Service - Chemical composition analysis - FIXED VERSION
✅ Fixed chemical formula mapping for Sulphate and Phenolic
✅ Proper status determination from database
✅ Better error handling
"""

import logging
from typing import Dict, Any, List

from app.db.mongo import db

logger = logging.getLogger(__name__)


# ✅ FIXED: Proper chemical formula mapping
CHEMICAL_FORMULAS = {
    # Physical parameters
    "pH": {
        "symbol": "pH",
        "formula": "-log[H⁺]",
        "ionic_form": "H+",
        "as_compound": None,
        "molecular_weight": None,
        "charge": 0,
        "category": "physical"
    },
    "Temperature": {
        "symbol": "T",
        "formula": "Temperature",
        "ionic_form": None,
        "as_compound": None,
        "molecular_weight": None,
        "charge": 0,
        "category": "physical"
    },
    "Electrical_Conductivity": {
        "symbol": "EC",
        "formula": "Electrical Conductivity",
        "ionic_form": None,
        "as_compound": None,
        "molecular_weight": None,
        "charge": 0,
        "category": "physical"
    },
    
    # Major cations
    "Calcium": {
        "symbol": "Ca",
        "formula": "Ca²⁺",
        "ionic_form": "Ca2+",
        "as_compound": "CaCO₃",
        "as_compound_alt": "CaCO3",
        "molecular_weight": 40.078,
        "charge": 2,
        "category": "major_cation"
    },
    "Magnesium": {
        "symbol": "Mg",
        "formula": "Mg²⁺",
        "ionic_form": "Mg2+",
        "as_compound": "MgCO₃",
        "as_compound_alt": "MgCO3",
        "molecular_weight": 24.305,
        "charge": 2,
        "category": "major_cation"
    },
    "Sodium": {
        "symbol": "Na",
        "formula": "Na⁺",
        "ionic_form": "Na+",
        "as_compound": "NaCl",
        "as_compound_alt": "NaCl",
        "molecular_weight": 22.99,
        "charge": 1,
        "category": "major_cation"
    },
    "Potassium": {
        "symbol": "K",
        "formula": "K⁺",
        "ionic_form": "K+",
        "as_compound": "KCl",
        "as_compound_alt": "KCl",
        "molecular_weight": 39.098,
        "charge": 1,
        "category": "major_cation"
    },
    
    # Major anions
    "Chloride": {
        "symbol": "Cl",
        "formula": "Cl⁻",
        "ionic_form": "Cl-",
        "as_compound": "NaCl",
        "as_compound_alt": "NaCl",
        "molecular_weight": 35.453,
        "charge": -1,
        "category": "major_anion"
    },
    # ✅ FIXED: Sulphate proper formula
    "Sulphate": {
        "symbol": "SO₄",
        "formula": "SO₄²⁻",
        "ionic_form": "SO4-2",
        "as_compound": "Na₂SO₄",
        "as_compound_alt": "Na2SO4",
        "molecular_weight": 96.06,
        "charge": -2,
        "category": "major_anion"
    },
    "Sulfate": {  # Alternative spelling
        "symbol": "SO₄",
        "formula": "SO₄²⁻",
        "ionic_form": "SO4-2",
        "as_compound": "Na₂SO₄",
        "as_compound_alt": "Na2SO4",
        "molecular_weight": 96.06,
        "charge": -2,
        "category": "major_anion"
    },
    "Nitrate": {
        "symbol": "NO₃",
        "formula": "NO₃⁻",
        "ionic_form": "NO3-",
        "as_compound": "NaNO₃",
        "as_compound_alt": "NaNO3",
        "molecular_weight": 62.004,
        "charge": -1,
        "category": "major_anion"
    },
    "Nitrite": {
        "symbol": "NO₂",
        "formula": "NO₂⁻",
        "ionic_form": "NO2-",
        "as_compound": "NaNO₂",
        "as_compound_alt": "NaNO2",
        "molecular_weight": 46.005,
        "charge": -1,
        "category": "major_anion"
    },
    "Fluoride": {
        "symbol": "F",
        "formula": "F⁻",
        "ionic_form": "F-",
        "as_compound": "NaF",
        "as_compound_alt": "NaF",
        "molecular_weight": 18.998,
        "charge": -1,
        "category": "major_anion"
    },
    
    # Heavy metals
    "Iron": {
        "symbol": "Fe",
        "formula": "Fe²⁺/Fe³⁺",
        "ionic_form": "Fe2+",
        "as_compound": "Fe₂O₃",
        "as_compound_alt": "Fe2O3",
        "molecular_weight": 55.845,
        "charge": 2,
        "category": "heavy_metal"
    },
    "Manganese": {
        "symbol": "Mn",
        "formula": "Mn²⁺",
        "ionic_form": "Mn2+",
        "as_compound": "MnO₂",
        "as_compound_alt": "MnO2",
        "molecular_weight": 54.938,
        "charge": 2,
        "category": "heavy_metal"
    },
    "Arsenic": {
        "symbol": "As",
        "formula": "As³⁺/As⁵⁺",
        "ionic_form": "As3+",
        "as_compound": "As₂O₃",
        "as_compound_alt": "As2O3",
        "molecular_weight": 74.922,
        "charge": 3,
        "category": "heavy_metal"
    },
    "Lead": {
        "symbol": "Pb",
        "formula": "Pb²⁺",
        "ionic_form": "Pb2+",
        "as_compound": "PbO",
        "as_compound_alt": "PbO",
        "molecular_weight": 207.2,
        "charge": 2,
        "category": "heavy_metal"
    },
    "Cadmium": {
        "symbol": "Cd",
        "formula": "Cd²⁺",
        "ionic_form": "Cd2+",
        "as_compound": "CdO",
        "as_compound_alt": "CdO",
        "molecular_weight": 112.411,
        "charge": 2,
        "category": "heavy_metal"
    },
    "Chromium": {
        "symbol": "Cr",
        "formula": "Cr³⁺/Cr⁶⁺",
        "ionic_form": "Cr3+",
        "as_compound": "Cr₂O₃",
        "as_compound_alt": "Cr2O3",
        "molecular_weight": 51.996,
        "charge": 3,
        "category": "heavy_metal"
    },
    "Mercury": {
        "symbol": "Hg",
        "formula": "Hg²⁺",
        "ionic_form": "Hg2+",
        "as_compound": "HgO",
        "as_compound_alt": "HgO",
        "molecular_weight": 200.59,
        "charge": 2,
        "category": "heavy_metal"
    },
    
    # Toxic compounds
    "Cyanide": {
        "symbol": "CN",
        "formula": "CN⁻",
        "ionic_form": "CN-",
        "as_compound": "NaCN",
        "as_compound_alt": "NaCN",
        "molecular_weight": 26.017,
        "charge": -1,
        "category": "toxic"
    },
    # ✅ FIXED: Phenolic Compounds proper formula
    "Phenolic_Compounds": {
        "symbol": "C₆H₅OH",
        "formula": "C₆H₅OH",
        "ionic_form": None,
        "as_compound": "Phenol",
        "as_compound_alt": None,
        "molecular_weight": 94.11,
        "charge": 0,
        "category": "organic"
    },
    
    # Others
    "Total_Dissolved_Solids": {
        "symbol": "TDS",
        "formula": "Total Dissolved Solids",
        "ionic_form": None,
        "as_compound": None,
        "molecular_weight": None,
        "charge": 0,
        "category": "physical"
    },
    "Total_Hardness": {
        "symbol": "Hardness",
        "formula": "Total Hardness as CaCO₃",
        "ionic_form": None,
        "as_compound": "CaCO₃",
        "molecular_weight": None,
        "charge": 0,
        "category": "physical"
    },
    "Total_Coliform": {
        "symbol": "Total_Coliform",
        "formula": None,
        "ionic_form": None,
        "as_compound": None,
        "molecular_weight": None,
        "charge": 0,
        "category": "biological"
    },
    "E_coli": {
        "symbol": "E_coli",
        "formula": None,
        "ionic_form": None,
        "as_compound": None,
        "molecular_weight": None,
        "charge": 0,
        "category": "biological"
    }
}


def get_chemical_formula(param_name: str) -> Dict:
    """Get chemical formula info for parameter - FIXED"""
    # Direct match
    if param_name in CHEMICAL_FORMULAS:
        return CHEMICAL_FORMULAS[param_name]
    
    # Try fuzzy match
    param_lower = param_name.lower().replace("_", "").replace(" ", "")
    
    for key, value in CHEMICAL_FORMULAS.items():
        key_lower = key.lower().replace("_", "").replace(" ", "")
        if param_lower in key_lower or key_lower in param_lower:
            return value
    
    # Default for unknown
    return {
        "symbol": param_name,
        "formula": None,
        "ionic_form": None,
        "as_compound": None,
        "molecular_weight": None,
        "charge": 0,
        "category": "unknown"
    }


class CompositionService:
    """Analyze chemical composition of water sample - FIXED VERSION"""
    
    async def analyze(
        self,
        parameters: Dict[str, Any],
        chemical_status: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Analyze chemical composition with FIXED chemical formulas
        """
        try:
            logger.info("🧪 Analyzing chemical composition")
            
            composition_params = []
            parameter_status = {}
            
            # Process each parameter
            for param_name, param_data in parameters.items():
                value = param_data.get("value")
                unit = param_data.get("unit", "")
                
                # Skip non-numeric
                if not isinstance(value, (int, float)):
                    continue
                
                # ✅ Get standard from database (FIXED)
                standard = await db.get_parameter_standard(param_name)
                
                # Determine status
                if standard:
                    status = await self._get_status(value, standard)
                    threshold = standard.get('thresholds', {})
                else:
                    status = "unknown"
                    threshold = None
                
                # Store status for summary
                parameter_status[param_name] = {"status": status}
                
                # ✅ GET CHEMICAL FORMULA INFO (FIXED)
                formula_info = get_chemical_formula(param_name)
                
                # Build parameter object with formulas
                composition_params.append({
                    "parameter_name": param_name,
                    "value": value,
                    "unit": unit or "",
                    "status": status,
                    "threshold": threshold,
                    
                    # ✅ Chemical formula fields (FIXED)
                    "chemical_symbol": formula_info.get("symbol"),
                    "chemical_formula": formula_info.get("formula"),
                    "ionic_form": formula_info.get("ionic_form"),
                    "as_compound": formula_info.get("as_compound"),
                    "as_compound_value": None,  # Can be calculated if needed
                    "molecular_weight": formula_info.get("molecular_weight"),
                    "charge": formula_info.get("charge"),
                    "category": formula_info.get("category"),
                })
            
            # Generate summary
            summary = await self._generate_summary(
                composition_params,
                parameter_status,
                chemical_status
            )
            
            logger.info(f"✅ Composition analysis complete - {len(composition_params)} parameters")
            
            return {
                "parameters": composition_params,
                "summary": summary
            }
            
        except Exception as e:
            logger.error(f"❌ Composition analysis failed: {e}")
            raise Exception(f"Composition analysis failed: {str(e)}")
    
    async def _get_status(self, value: float, standard: Dict) -> str:
        """
        Determine status based on thresholds
        
        Returns: "optimal", "good", "warning", "critical", "unknown"
        """
        thresholds = standard.get('thresholds', {})
        
        for level in ['optimal', 'good', 'warning', 'critical']:
            threshold = thresholds.get(level, {})
            
            if not threshold:
                continue
            
            min_val = threshold.get('min', float('-inf'))
            max_val = threshold.get('max', float('inf'))
            
            if min_val <= value <= max_val:
                return level
        
        return "unknown"
    
    async def _generate_summary(
        self,
        composition_params: List[Dict],
        parameter_status: Dict,
        chemical_status: Dict
    ) -> str:
        """Generate AI-powered summary of composition"""
        # Count by category
        categories = {}
        for param in composition_params:
            cat = param.get("category", "unknown")
            categories[cat] = categories.get(cat, 0) + 1
        
        # Count statuses
        status_counts = {
            'optimal': 0,
            'good': 0,
            'warning': 0,
            'critical': 0,
            'unknown': 0
        }
        
        for param in composition_params:
            status = param.get('status', 'unknown')
            if status in status_counts:
                status_counts[status] += 1
        
        total = sum(status_counts.values())
        
        # Generate summary parts
        summary_parts = []
        
        # Category breakdown
        if categories:
            cat_parts = []
            cat_order = ["major_cation", "major_anion", "heavy_metal", "nutrient", "physical", "biological", "organic"]
            for cat in cat_order:
                if cat in categories:
                    cat_parts.append(f"{categories[cat]} {cat.replace('_', ' ')}")
            if cat_parts:
                summary_parts.append(f"Detected {', '.join(cat_parts)} parameters")
        
        # Status summary
        if status_counts['critical'] > 0:
            summary_parts.append(f"⚠️ {status_counts['critical']} parameter(s) in critical range")
        
        if status_counts['warning'] > 0:
            summary_parts.append(f"{status_counts['warning']} parameter(s) need attention")
        
        if status_counts['optimal'] + status_counts['good'] >= total * 0.7:
            good_count = status_counts['optimal'] + status_counts['good']
            summary_parts.append(f"{good_count} parameters within acceptable ranges")
        
        # Add saturation info
        saturation_indices = chemical_status.get('saturation_indices', [])
        oversaturated = [si for si in saturation_indices if si.get('si_value', -999) > 0.5 and si.get('si_value') != -999]
        
        if oversaturated:
            minerals = [si['mineral_name'] for si in oversaturated[:3]]  # Top 3
            summary_parts.append(f"Oversaturation detected: {', '.join(minerals)}")
        
        # Combine summary
        if summary_parts:
            summary = ". ".join(summary_parts) + "."
        else:
            summary = "Water composition is within acceptable ranges."
        
        return summary