"""
Chemical Formula Mappings
Complete database of water quality parameters with their chemical representations
"""

from typing import Dict, Any


# ===============================
# PARAMETER CHEMICAL FORMULAS
# ===============================
PARAMETER_FORMULAS: Dict[str, Dict[str, Any]] = {
    # Major Cations
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
        "molecular_weight": 22.990,
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
    
    # Major Anions
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
    "Sulfate": {
        "symbol": "SO₄",
        "formula": "SO₄²⁻",
        "ionic_form": "SO4^2-",
        "as_compound": "Na₂SO₄",
        "as_compound_alt": "Na2SO4",
        "molecular_weight": 96.06,
        "charge": -2,
        "category": "major_anion"
    },
    "Bicarbonate": {
        "symbol": "HCO₃",
        "formula": "HCO₃⁻",
        "ionic_form": "HCO3-",
        "as_compound": "NaHCO₃",
        "as_compound_alt": "NaHCO3",
        "molecular_weight": 61.016,
        "charge": -1,
        "category": "major_anion"
    },
    "Carbonate": {
        "symbol": "CO₃",
        "formula": "CO₃²⁻",
        "ionic_form": "CO3^2-",
        "as_compound": "Na₂CO₃",
        "as_compound_alt": "Na2CO3",
        "molecular_weight": 60.008,
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
    
    # Alkalinity & Hardness
    "Alkalinity": {
        "symbol": "Alk",
        "formula": "CaCO₃ equiv.",
        "ionic_form": "HCO3- + CO3^2-",
        "as_compound": "CaCO₃",
        "as_compound_alt": "CaCO3",
        "molecular_weight": 100.086,
        "charge": 0,
        "category": "alkalinity"
    },
    "Total Hardness": {
        "symbol": "TH",
        "formula": "CaCO₃ equiv.",
        "ionic_form": "Ca2+ + Mg2+",
        "as_compound": "CaCO₃",
        "as_compound_alt": "CaCO3",
        "molecular_weight": 100.086,
        "charge": 0,
        "category": "hardness"
    },
    "Calcium Hardness": {
        "symbol": "Ca-H",
        "formula": "CaCO₃ equiv.",
        "ionic_form": "Ca2+",
        "as_compound": "CaCO₃",
        "as_compound_alt": "CaCO3",
        "molecular_weight": 100.086,
        "charge": 0,
        "category": "hardness"
    },
    "Magnesium Hardness": {
        "symbol": "Mg-H",
        "formula": "CaCO₃ equiv.",
        "ionic_form": "Mg2+",
        "as_compound": "CaCO₃",
        "as_compound_alt": "CaCO3",
        "molecular_weight": 100.086,
        "charge": 0,
        "category": "hardness"
    },
    
    # Heavy Metals
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
    "Copper": {
        "symbol": "Cu",
        "formula": "Cu²⁺",
        "ionic_form": "Cu2+",
        "as_compound": "CuO",
        "as_compound_alt": "CuO",
        "molecular_weight": 63.546,
        "charge": 2,
        "category": "heavy_metal"
    },
    "Zinc": {
        "symbol": "Zn",
        "formula": "Zn²⁺",
        "ionic_form": "Zn2+",
        "as_compound": "ZnO",
        "as_compound_alt": "ZnO",
        "molecular_weight": 65.38,
        "charge": 2,
        "category": "heavy_metal"
    },
    
    # Other Parameters
    "Silica": {
        "symbol": "SiO₂",
        "formula": "SiO₂",
        "ionic_form": "SiO2",
        "as_compound": "SiO₂",
        "as_compound_alt": "SiO2",
        "molecular_weight": 60.084,
        "charge": 0,
        "category": "other"
    },
    "Phosphate": {
        "symbol": "PO₄",
        "formula": "PO₄³⁻",
        "ionic_form": "PO4^3-",
        "as_compound": "Na₃PO₄",
        "as_compound_alt": "Na3PO4",
        "molecular_weight": 94.971,
        "charge": -3,
        "category": "nutrient"
    },
    "Ammonia": {
        "symbol": "NH₃",
        "formula": "NH₃",
        "ionic_form": "NH3",
        "as_compound": "NH₄Cl",
        "as_compound_alt": "NH4Cl",
        "molecular_weight": 17.031,
        "charge": 0,
        "category": "nutrient"
    },
    "Ammonium": {
        "symbol": "NH₄",
        "formula": "NH₄⁺",
        "ionic_form": "NH4+",
        "as_compound": "NH₄Cl",
        "as_compound_alt": "NH4Cl",
        "molecular_weight": 18.038,
        "charge": 1,
        "category": "nutrient"
    },
    "Chlorine": {
        "symbol": "Cl₂",
        "formula": "Cl₂",
        "ionic_form": "Cl2",
        "as_compound": "Cl₂",
        "as_compound_alt": "Cl2",
        "molecular_weight": 70.906,
        "charge": 0,
        "category": "disinfectant"
    },
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
    
    # Physical Parameters (no chemical formula)
    "pH": {
        "symbol": "pH",
        "formula": "-log[H⁺]",
        "ionic_form": "H+",
        "as_compound": None,
        "as_compound_alt": None,
        "molecular_weight": None,
        "charge": 0,
        "category": "physical"
    },
    "Temperature": {
        "symbol": "T",
        "formula": None,
        "ionic_form": None,
        "as_compound": None,
        "as_compound_alt": None,
        "molecular_weight": None,
        "charge": 0,
        "category": "physical"
    },
    "TDS": {
        "symbol": "TDS",
        "formula": "Total Dissolved Solids",
        "ionic_form": "Mixed ions",
        "as_compound": None,
        "as_compound_alt": None,
        "molecular_weight": None,
        "charge": 0,
        "category": "physical"
    },
    "Total Dissolved Solid (TDS)": {
        "symbol": "TDS",
        "formula": "Total Dissolved Solids",
        "ionic_form": "Mixed ions",
        "as_compound": None,
        "as_compound_alt": None,
        "molecular_weight": None,
        "charge": 0,
        "category": "physical"
    },
    "Conductivity": {
        "symbol": "EC",
        "formula": "Electrical Conductivity",
        "ionic_form": None,
        "as_compound": None,
        "as_compound_alt": None,
        "molecular_weight": None,
        "charge": 0,
        "category": "physical"
    },
    "Turbidity": {
        "symbol": "NTU",
        "formula": None,
        "ionic_form": None,
        "as_compound": None,
        "as_compound_alt": None,
        "molecular_weight": None,
        "charge": 0,
        "category": "physical"
    },
    
    # Organic Parameters
    "BOD": {
        "symbol": "BOD",
        "formula": "Biological Oxygen Demand",
        "ionic_form": None,
        "as_compound": None,
        "as_compound_alt": None,
        "molecular_weight": None,
        "charge": 0,
        "category": "organic"
    },
    "COD": {
        "symbol": "COD",
        "formula": "Chemical Oxygen Demand",
        "ionic_form": None,
        "as_compound": None,
        "as_compound_alt": None,
        "molecular_weight": None,
        "charge": 0,
        "category": "organic"
    },
    "TOC": {
        "symbol": "TOC",
        "formula": "Total Organic Carbon",
        "ionic_form": None,
        "as_compound": None,
        "as_compound_alt": None,
        "molecular_weight": None,
        "charge": 0,
        "category": "organic"
    }
}


# ===============================
# HELPER FUNCTIONS
# ===============================
def get_chemical_formula(parameter_name: str) -> Dict[str, Any]:
    """
    Get chemical formula information for a parameter
    
    Args:
        parameter_name: Name of parameter (e.g., "Calcium", "pH")
        
    Returns:
        Dictionary with chemical formula info, or None if not found
    """
    # Try exact match first
    if parameter_name in PARAMETER_FORMULAS:
        return PARAMETER_FORMULAS[parameter_name]
    
    # Try case-insensitive match
    for key, value in PARAMETER_FORMULAS.items():
        if key.lower() == parameter_name.lower():
            return value
    
    # Try partial match
    param_lower = parameter_name.lower()
    for key, value in PARAMETER_FORMULAS.items():
        if param_lower in key.lower() or key.lower() in param_lower:
            return value
    
    # Not found - return default
    return {
        "symbol": parameter_name,
        "formula": None,
        "ionic_form": None,
        "as_compound": None,
        "as_compound_alt": None,
        "molecular_weight": None,
        "charge": 0,
        "category": "unknown"
    }


def convert_to_compound(value: float, unit: str, from_element: str, to_compound: str) -> float:
    """
    Convert element concentration to compound concentration
    
    Example: Ca (40 mg/L) → CaCO3 (100 mg/L)
    
    Args:
        value: Concentration value
        unit: Unit (must be mg/L)
        from_element: Element symbol (e.g., "Ca")
        to_compound: Compound formula (e.g., "CaCO3")
        
    Returns:
        Converted value
    """
    if unit != "mg/L":
        return value
    
    # Conversion factors (element → CaCO3)
    conversion_factors = {
        "Ca": 2.497,   # Ca → CaCO3
        "Mg": 4.116,   # Mg → CaCO3
        "Fe": 1.792,   # Fe → CaCO3
        "Mn": 1.822,   # Mn → CaCO3
    }
    
    factor = conversion_factors.get(from_element, 1.0)
    return value * factor


def get_parameter_category(parameter_name: str) -> str:
    """Get category of parameter"""
    formula_info = get_chemical_formula(parameter_name)
    return formula_info.get("category", "unknown")