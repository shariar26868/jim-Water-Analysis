
# """
# Pydantic Models for Request/Response Validation
# Fully dynamic - no hard-coded parameter lists
# WITH Chemical Formula Support
# """

# from pydantic import BaseModel, Field, validator
# from typing import Dict, List, Optional, Any, Union
# from datetime import datetime
# from enum import Enum


# # ========== ENUMS ==========

# class StatusEnum(str, Enum):
#     optimal = "optimal"
#     good = "good"
#     warning = "warning"
#     critical = "critical"
#     unknown = "unknown"


# class ComplianceStatusEnum(str, Enum):
#     passed = "Passed"
#     failed = "Failed"
#     pending = "Pending"
#     not_applicable = "N/A"


# # ========== EXTRACTED PARAMETER ==========

# class ExtractedParameter(BaseModel):
#     """Single extracted parameter from PDF"""
#     value: Union[float, int, str]
#     unit: Optional[str] = None
#     detection_limit: Optional[float] = None
    
#     class Config:
#         json_schema_extra = {
#             "example": {
#                 "value": 7.8,
#                 "unit": None,
#                 "detection_limit": None
#             }
#         }


# # ========== CHEMICAL STATUS ==========

# class SaturationIndex(BaseModel):
#     """Saturation index for a mineral"""
#     mineral_name: str
#     si_value: float
#     status: str


# class ChemicalStatus(BaseModel):
#     """Chemical status from PHREEQC"""
#     input_parameters: Dict[str, Any]
#     solution_parameters: Dict[str, Any]
#     saturation_indices: List[SaturationIndex]
#     ionic_strength: float
#     charge_balance_error: float
#     database_used: str


# # ========== GRAPH ==========

# class GraphResponse(BaseModel):
#     """Graph generation response"""
#     graph_url: str
#     graph_type: str
#     color_mapping: Dict[str, str]
#     created_at: datetime


# class GraphModifyRequest(BaseModel):
#     """Request to modify graph with prompt"""
#     report_id: str
#     prompt: str
    
#     class Config:
#         json_schema_extra = {
#             "example": {
#                 "report_id": "WQR-2024-001",
#                 "prompt": "Make pH bar green and TDS bar red"
#             }
#         }


# # ========== SCORING ==========

# class ScoreComponent(BaseModel):
#     """Individual score component"""
#     name: str
#     score: float
#     max_score: float
#     weight: float


# class TotalScore(BaseModel):
#     """Total analysis score"""
#     overall_score: float
#     max_score: float = 100
#     rating: str
#     components: List[ScoreComponent]


# # ========== WATER QUALITY REPORT ==========

# class WaterQualityIndex(BaseModel):
#     """Water Quality Index"""
#     score: float
#     max_score: float = 100
#     rating: str


# class ComplianceScore(BaseModel):
#     """Compliance score"""
#     score: float
#     percentage: str
#     rating: str


# class RiskFactor(BaseModel):
#     """Risk factor assessment"""
#     score: float
#     max_score: float = 10
#     severity: str


# class QualityReport(BaseModel):
#     """Complete water quality report"""
#     water_quality_index: WaterQualityIndex
#     compliance_score: ComplianceScore
#     risk_factor: RiskFactor


# # ========== CHEMICAL COMPOSITION ========== 
# # ✅ UPDATED: Added chemical formula fields

# class CompositionParameter(BaseModel):
#     """Single composition parameter with chemical formula support"""
#     parameter_name: str
#     value: float
#     unit: Optional[str] = ""  # ✅ Optional with default empty string
#     status: StatusEnum
#     threshold: Optional[Dict[str, Any]] = None
    
#     # ✅ NEW: Chemical formula fields
#     chemical_symbol: Optional[str] = None           # "Ca"
#     chemical_formula: Optional[str] = None          # "Ca²⁺"
#     ionic_form: Optional[str] = None                # "Ca2+"
#     as_compound: Optional[str] = None               # "CaCO₃"
#     as_compound_value: Optional[float] = None       # Converted value as CaCO3
#     molecular_weight: Optional[float] = None        # 40.078
#     charge: Optional[int] = None                    # 2
#     category: Optional[str] = None                  # "major_cation"
    
#     class Config:
#         json_schema_extra = {
#             "example": {
#                 "parameter_name": "Calcium",
#                 "value": 85.5,
#                 "unit": "mg/L",
#                 "status": "good",
#                 "threshold": {"optimal": {"min": 0, "max": 100}},
#                 "chemical_symbol": "Ca",
#                 "chemical_formula": "Ca²⁺",
#                 "ionic_form": "Ca2+",
#                 "as_compound": "CaCO₃",
#                 "as_compound_value": 213.52,
#                 "molecular_weight": 40.078,
#                 "charge": 2,
#                 "category": "major_cation"
#             }
#         }


# class ChemicalComposition(BaseModel):
#     """Chemical composition report"""
#     parameters: List[CompositionParameter]
#     summary: str


# # ========== BIOLOGICAL INDICATORS ==========

# class BiologicalIndicator(BaseModel):
#     """Single biological indicator"""
#     indicator_name: str
#     value: Union[float, str]
#     unit: Optional[str] = None
#     status: str
#     risk_level: str


# class BiologicalReport(BaseModel):
#     """Biological indicators report"""
#     indicators: List[BiologicalIndicator]
#     overall_status: str


# # ========== COMPLIANCE CHECKLIST ==========

# class ComplianceItem(BaseModel):
#     """Single compliance checklist item"""
#     parameter: str
#     standard: str
#     status: ComplianceStatusEnum
#     actual_value: Optional[float] = None
#     required_value: Optional[str] = None
#     remarks: Optional[str] = None


# class ComplianceChecklist(BaseModel):
#     """Compliance checklist"""
#     items: List[ComplianceItem]
#     overall_compliance: float
#     passed_count: int
#     failed_count: int
#     pending_count: int


# # ========== CONTAMINATION RISK ==========

# class ContaminantRisk(BaseModel):
#     """Single contaminant risk"""
#     contaminant_name: str
#     value: float
#     unit: str
#     risk_level: str
#     threshold: Optional[float] = None


# class ContaminationRisk(BaseModel):
#     """Contamination risk analysis"""
#     heavy_metals: List[ContaminantRisk]
#     organic_compounds: List[ContaminantRisk]
#     microbiological: List[ContaminantRisk]
#     overall_severity: str
#     risk_score: float


# # ========== COMPLETE ANALYSIS RESPONSE ========== 

# class WaterAnalysisResponse(BaseModel):
#     """Complete water analysis response (all 10 features)"""
    
#     # Feature 10: Report ID
#     report_id: str
    
#     # Feature 1: Extracted Parameters
#     extracted_parameters: Dict[str, ExtractedParameter]
    
#     # Feature 2: Parameter Comparison Graph
#     parameter_graph: GraphResponse
    
#     # Feature 3: Chemical Status
#     chemical_status: ChemicalStatus
    
#     # Feature 4: Total Analysis Score
#     total_score: TotalScore
    
#     # Feature 5: Water Quality Report
#     quality_report: QualityReport
    
#     # Feature 6: Chemical Composition
#     chemical_composition: ChemicalComposition
    
#     # Feature 7: Biological Indicators
#     biological_indicators: BiologicalReport
    
#     # Feature 8: Compliance Checklist
#     compliance_checklist: ComplianceChecklist
    
#     # Feature 9: Contamination Risk
#     contamination_risk: ContaminationRisk
    
#     # Metadata
#     sample_location: Optional[str] = None
#     sample_date: Optional[datetime] = None
#     created_at: datetime
    
#     # ✅ Date validator
#     @validator('sample_date', pre=True)
#     def parse_sample_date(cls, v):
#         """Parse sample_date from various string formats"""
#         if v is None:
#             return None
        
#         if isinstance(v, datetime):
#             return v
        
#         if isinstance(v, str):
#             # Try multiple date formats
#             for fmt in ["%m/%d/%Y", "%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d"]:
#                 try:
#                     return datetime.strptime(v, fmt)
#                 except ValueError:
#                     continue
            
#             # If all fail, use current time
#             return datetime.utcnow()
        
#         return v
    
#     class Config:
#         json_schema_extra = {
#             "example": {
#                 "report_id": "WQR-2024-001",
#                 "extracted_parameters": {
#                     "pH": {"value": 7.8, "unit": None},
#                     "Calcium": {"value": 85.5, "unit": "mg/L"}
#                 },
#                 "total_score": {
#                     "overall_score": 85.0,
#                     "rating": "Good"
#                 }
#             }
#         }


# # ========== API REQUESTS ==========

# class AnalyzeRequest(BaseModel):
#     """Request for water analysis (file uploaded separately)"""
#     sample_location: Optional[str] = None
#     sample_date: Optional[datetime] = None
#     custom_standards: Optional[List[str]] = None


# class RecalculateRequest(BaseModel):
#     """Request to recalculate with adjusted parameters"""
#     report_id: str
#     adjusted_parameters: Dict[str, float]
    
#     class Config:
#         json_schema_extra = {
#             "example": {
#                 "report_id": "WQR-2024-001",
#                 "adjusted_parameters": {
#                     "Calcium": 90.0,
#                     "Magnesium": 45.0
#                 }
#             }
#         }


# # ========== REPORT HISTORY ==========

# class ReportSummary(BaseModel):
#     """Summary for report history list"""
#     report_id: str
#     sample_location: Optional[str]
#     sample_date: Optional[datetime]
#     created_at: datetime
#     overall_score: float
#     wqi_rating: str


# class ReportHistoryResponse(BaseModel):
#     """Report history response"""
#     reports: List[ReportSummary]
#     total_count: int
#     page: int
#     page_size: int


# # ========== ERROR RESPONSES ==========

# class ErrorResponse(BaseModel):
#     """Standard error response"""
#     error: str
#     detail: Optional[str] = None
#     timestamp: datetime = Field(default_factory=datetime.utcnow)


# # ========== PARAMETER STANDARD (Admin) ==========

# class ParameterStandard(BaseModel):
#     """Parameter threshold standard"""
#     parameter_name: str
#     unit: Optional[str] = None
#     thresholds: Dict[str, Dict[str, float]]
#     standards: Optional[Dict[str, Dict[str, float]]] = None
#     description: Optional[str] = None
#     health_impact: Optional[Dict[str, str]] = None


# # ========== CALCULATION FORMULA (Admin) ==========

# class CalculationFormula(BaseModel):
#     """Calculation formula definition"""
#     formula_name: str
#     formula_type: str
#     required_parameters: List[str]
#     formula_expression: str
#     interpretation: Optional[Dict[str, Any]] = None
#     unit: Optional[str] = None
#     description: Optional[str] = None




"""
Pydantic Models for Request/Response Validation
Fully dynamic - no hard-coded parameter lists
WITH Chemical Formula Support
✅ UPDATED: Added Water Indices, Cooling Tower, and Corrosion models
"""

from pydantic import BaseModel, Field, validator
from typing import Dict, List, Optional, Any, Union
from datetime import datetime
from enum import Enum


# ========== ENUMS ==========

class StatusEnum(str, Enum):
    optimal = "optimal"
    good = "good"
    warning = "warning"
    critical = "critical"
    unknown = "unknown"


class ComplianceStatusEnum(str, Enum):
    passed = "Passed"
    failed = "Failed"
    pending = "Pending"
    not_applicable = "N/A"


# ========== EXTRACTED PARAMETER ==========

class ExtractedParameter(BaseModel):
    """Single extracted parameter from PDF"""
    value: Union[float, int, str]
    unit: Optional[str] = None
    detection_limit: Optional[float] = None
    
    class Config:
        json_schema_extra = {
            "example": {
                "value": 7.8,
                "unit": None,
                "detection_limit": None
            }
        }


# ========== CHEMICAL STATUS ==========

class SaturationIndex(BaseModel):
    """Saturation index for a mineral"""
    mineral_name: str
    si_value: float
    status: Optional[str] = None
    log_IAP: Optional[float] = None
    log_K: Optional[float] = None
    phase: Optional[str] = None
    chemical_formula: Optional[str] = None


class ChemicalStatus(BaseModel):
    """Chemical status from PHREEQC"""
    input_parameters: Dict[str, Any]
    solution_parameters: Dict[str, Any]
    saturation_indices: List[SaturationIndex]
    ionic_strength: float
    charge_balance_error: float
    database_used: str


# ========== GRAPH ==========

class GraphResponse(BaseModel):
    """Graph generation response"""
    graph_url: str
    graph_type: str
    color_mapping: Dict[str, str]
    created_at: datetime


class GraphModifyRequest(BaseModel):
    """Request to modify graph with prompt"""
    report_id: str
    prompt: str
    
    class Config:
        json_schema_extra = {
            "example": {
                "report_id": "WQR-2024-001",
                "prompt": "Make pH bar green and TDS bar red"
            }
        }


# ========== SCORING ==========

class ScoreComponent(BaseModel):
    """Individual score component"""
    name: str
    score: float
    max_score: float
    weight: float


class TotalScore(BaseModel):
    """Total analysis score"""
    overall_score: float
    max_score: float = 100
    rating: str
    components: List[ScoreComponent]


# ========== WATER QUALITY REPORT ==========

class WaterQualityIndex(BaseModel):
    """Water Quality Index"""
    score: float
    max_score: float = 100
    rating: str


class ComplianceScore(BaseModel):
    """Compliance score"""
    score: float
    percentage: str
    rating: str


class RiskFactor(BaseModel):
    """Risk factor assessment"""
    score: float
    max_score: float = 10
    severity: str


class QualityReport(BaseModel):
    """Complete water quality report"""
    water_quality_index: WaterQualityIndex
    compliance_score: ComplianceScore
    risk_factor: RiskFactor


# ========== CHEMICAL COMPOSITION ==========

class CompositionParameter(BaseModel):
    """Single composition parameter with chemical formula support"""
    parameter_name: str
    value: float
    unit: Optional[str] = ""
    status: StatusEnum
    threshold: Optional[Dict[str, Any]] = None
    
    # Chemical formula fields
    chemical_symbol: Optional[str] = None
    chemical_formula: Optional[str] = None
    ionic_form: Optional[str] = None
    as_compound: Optional[str] = None
    as_compound_value: Optional[float] = None
    molecular_weight: Optional[float] = None
    charge: Optional[int] = None
    category: Optional[str] = None
    
    class Config:
        json_schema_extra = {
            "example": {
                "parameter_name": "Calcium",
                "value": 85.5,
                "unit": "mg/L",
                "status": "good",
                "threshold": {"optimal": {"min": 0, "max": 100}},
                "chemical_symbol": "Ca",
                "chemical_formula": "Ca²⁺",
                "ionic_form": "Ca2+",
                "as_compound": "CaCO₃",
                "as_compound_value": 213.52,
                "molecular_weight": 40.078,
                "charge": 2,
                "category": "major_cation"
            }
        }


class ChemicalComposition(BaseModel):
    """Chemical composition report"""
    parameters: List[CompositionParameter]
    summary: str


# ========== BIOLOGICAL INDICATORS ==========

class BiologicalIndicator(BaseModel):
    """Single biological indicator"""
    indicator_name: str
    value: Union[float, str]
    unit: Optional[str] = None
    status: str
    risk_level: str


class BiologicalReport(BaseModel):
    """Biological indicators report"""
    indicators: List[BiologicalIndicator]
    overall_status: str


# ========== COMPLIANCE CHECKLIST ==========

class ComplianceItem(BaseModel):
    """Single compliance checklist item"""
    parameter: str
    standard: str
    status: ComplianceStatusEnum
    actual_value: Optional[float] = None
    required_value: Optional[str] = None
    remarks: Optional[str] = None


class ComplianceChecklist(BaseModel):
    """Compliance checklist"""
    items: List[ComplianceItem]
    overall_compliance: float
    passed_count: int
    failed_count: int
    pending_count: int


# ========== CONTAMINATION RISK ==========

class ContaminantRisk(BaseModel):
    """Single contaminant risk"""
    contaminant_name: str
    value: float
    unit: str
    risk_level: str
    threshold: Optional[float] = None


class ContaminationRisk(BaseModel):
    """Contamination risk analysis"""
    heavy_metals: List[ContaminantRisk]
    organic_compounds: List[ContaminantRisk]
    microbiological: List[ContaminantRisk]
    overall_severity: str
    risk_score: float


# ========================================
# 🆕 NEW: WATER CHEMISTRY INDICES MODELS
# ========================================

class LarsonSkoldIndex(BaseModel):
    """Larson-Skold Corrosion Index"""
    index: Optional[float] = None
    interpretation: str
    risk_level: str
    components: Optional[Dict[str, float]] = None


class StiffDavisIndex(BaseModel):
    """Stiff & Davis Index"""
    index: Optional[float] = None
    interpretation: str
    risk: str
    components: Optional[Dict[str, float]] = None


class PuckoriusIndex(BaseModel):
    """Puckorius Scaling Index"""
    index: Optional[float] = None
    interpretation: str
    risk: str
    components: Optional[Dict[str, float]] = None


class CCPPResult(BaseModel):
    """Calcium Carbonate Precipitation Potential"""
    ccpp_ppm: float
    interpretation: str
    risk: str
    calcite_moles: Optional[float] = None


class LSIResult(BaseModel):
    """Langelier Saturation Index"""
    lsi: float
    interpretation: str
    risk: str
    pH_actual: float
    pHs: float


class RyznarResult(BaseModel):
    """Ryznar Index"""
    ri: float
    interpretation: str
    risk: str
    pH_actual: float
    pHs: float


class DissolvedOxygenResult(BaseModel):
    """Dissolved Oxygen estimation"""
    do_ppm: float
    temp_water_c: float
    temp_wetbulb_c: float


class CorrosionRateResult(BaseModel):
    """Corrosion rate prediction"""
    cr_mpy: float  # mils per year
    cr_base_mpy: Optional[float] = None
    total_inhibition_percent: Optional[float] = None
    rating: str  # Excellent, Good, Fair, Poor


class WaterIndices(BaseModel):
    """Complete water chemistry indices analysis"""
    larson_skold: Optional[LarsonSkoldIndex] = None
    stiff_davis: Optional[StiffDavisIndex] = None
    puckorius: Optional[PuckoriusIndex] = None
    ccpp: Optional[CCPPResult] = None
    lsi: Optional[LSIResult] = None
    ryznar: Optional[RyznarResult] = None
    dissolved_oxygen: Optional[DissolvedOxygenResult] = None
    
    class Config:
        json_schema_extra = {
            "example": {
                "lsi": {
                    "lsi": -0.3,
                    "interpretation": "Corrosive",
                    "risk": "Corrosive",
                    "pH_actual": 7.8,
                    "pHs": 8.1
                },
                "ccpp": {
                    "ccpp_ppm": -12.5,
                    "interpretation": "Slight Dissolution",
                    "risk": "Low Corrosion",
                    "calcite_moles": -0.000125
                }
            }
        }


# ========================================
# 🆕 NEW: COOLING TOWER MODELS
# ========================================

class CyclesOfConcentration(BaseModel):
    """Cycles of Concentration calculation"""
    coc: Optional[float] = None
    tracer_ion: str
    base_value: Optional[float] = None
    concentrated_value: Optional[float] = None


class EvaporationRate(BaseModel):
    """Evaporation rate calculation"""
    evaporation_rate_gpm: float
    recirculation_rate_gpm: float
    delta_t_f: float
    evaporation_factor_percent: float


class BlowdownRate(BaseModel):
    """Blowdown rate calculation"""
    blowdown_rate_gpm: Optional[float] = None
    evaporation_rate_gpm: float
    coc: float


class MakeupRate(BaseModel):
    """Makeup rate calculation"""
    makeup_rate_gpm: float
    evaporation_rate_gpm: float
    blowdown_rate_gpm: float
    drift_rate_gpm: float
    drift_percent: float


class TowerRange(BaseModel):
    """Cooling tower range"""
    range_f: float
    hot_water_temp_f: float
    cold_water_temp_f: float


class ApproachTemperature(BaseModel):
    """Approach temperature"""
    approach_f: float
    cold_water_temp_f: float
    wet_bulb_temp_f: float


class TowerEfficiency(BaseModel):
    """Tower efficiency"""
    efficiency_percent: Optional[float] = None
    range_f: float
    approach_f: float


class HeatLoad(BaseModel):
    """Heat load calculation"""
    heat_load_btu_hr: float
    recirculation_rate_gpm: float
    range_f: float


class CoolingTons(BaseModel):
    """Cooling tons conversion"""
    cooling_tons: float
    recirculation_rate_gpm: Optional[float] = None
    range_f: float


class ChemicalDosage(BaseModel):
    """Chemical dosage calculations"""
    chemical_lbs_per_day: Optional[float] = None
    chemical_lbs_per_year: Optional[float] = None
    product_dosage_ppm: float
    blowdown_rate_gpm: Optional[float] = None
    cost_per_million_lbs_bd: Optional[float] = None


class CoolingTowerAnalysis(BaseModel):
    """Complete cooling tower analysis"""
    range: TowerRange
    approach: ApproachTemperature
    efficiency: TowerEfficiency
    evaporation: EvaporationRate
    blowdown: BlowdownRate
    makeup: MakeupRate
    heat_load: HeatLoad
    cooling_tons: CoolingTons
    
    class Config:
        json_schema_extra = {
            "example": {
                "range": {"range_f": 10.0, "hot_water_temp_f": 95, "cold_water_temp_f": 85},
                "evaporation": {"evaporation_rate_gpm": 200, "recirculation_rate_gpm": 10000},
                "blowdown": {"blowdown_rate_gpm": 50, "coc": 4.0},
                "makeup": {"makeup_rate_gpm": 260, "evaporation_rate_gpm": 200}
            }
        }


# ========================================
# 🆕 NEW: CORROSION PREDICTIONS
# ========================================

class CorrosionPredictions(BaseModel):
    """Corrosion rate predictions for different metals"""
    mild_steel: Optional[CorrosionRateResult] = None
    copper: Optional[CorrosionRateResult] = None
    admiralty_brass: Optional[CorrosionRateResult] = None
    
    class Config:
        json_schema_extra = {
            "example": {
                "mild_steel": {
                    "cr_mpy": 2.5,
                    "rating": "Excellent"
                },
                "copper": {
                    "cr_mpy": 0.8,
                    "rating": "Excellent"
                }
            }
        }


# ========================================
# 🆕 NEW: BATCH SATURATION ANALYSIS
# ========================================

class GridPoint(BaseModel):
    """Single grid point for 3D analysis"""
    pH: float
    CoC: float
    temp: float


class BatchSaturationResult(BaseModel):
    """Result from single grid point"""
    pH: float
    CoC: float
    temp: float
    saturation_indices: List[SaturationIndex]
    ionic_strength: float
    charge_balance_error: float


class BatchSaturationAnalysis(BaseModel):
    """3D batch saturation analysis results"""
    grid_points: List[GridPoint]
    results: List[BatchSaturationResult]
    database_used: str
    
    class Config:
        json_schema_extra = {
            "example": {
                "grid_points": [
                    {"pH": 7.0, "CoC": 2.0, "temp": 25},
                    {"pH": 8.0, "CoC": 3.0, "temp": 30}
                ],
                "database_used": "pitzer.dat"
            }
        }


# ========================================
# ✅ UPDATED: COMPLETE ANALYSIS RESPONSE
# ========================================

class WaterAnalysisResponse(BaseModel):
    """
    Complete water analysis response
    ✅ UPDATED: Now includes water indices, cooling tower, and corrosion predictions
    """
    
    # Feature 10: Report ID
    report_id: str
    
    # Feature 1: Extracted Parameters
    extracted_parameters: Dict[str, ExtractedParameter]
    
    # Feature 2: Parameter Comparison Graph
    parameter_graph: GraphResponse
    
    # Feature 3: Chemical Status
    chemical_status: ChemicalStatus
    
    # Feature 4: Total Analysis Score
    total_score: TotalScore
    
    # Feature 5: Water Quality Report
    quality_report: QualityReport
    
    # Feature 6: Chemical Composition
    chemical_composition: ChemicalComposition
    
    # Feature 7: Biological Indicators
    biological_indicators: BiologicalReport
    
    # Feature 8: Compliance Checklist
    compliance_checklist: ComplianceChecklist
    
    # Feature 9: Contamination Risk
    contamination_risk: ContaminationRisk
    
    # 🆕 NEW: Water Chemistry Indices
    water_indices: Optional[WaterIndices] = None
    
    # 🆕 NEW: Cooling Tower Analysis (if applicable)
    cooling_tower: Optional[CoolingTowerAnalysis] = None
    
    # 🆕 NEW: Corrosion Predictions
    corrosion_predictions: Optional[CorrosionPredictions] = None
    
    # Metadata
    sample_location:    Optional[str]      = None
    sample_date:        Optional[datetime] = None
    analysis_date:      Optional[datetime] = None
    water_use_type:     Optional[str]      = None   # makeup_water | cooling_tower_water | process_water
    water_source_type:  Optional[str]      = None   # city | surface | well | sea
    location:           Optional[str]      = None
    report_name:        Optional[str]      = None
    customer_id:        Optional[str]      = None
    customer_name:      Optional[str]      = None
    asset_id:           Optional[str]      = None
    created_at:         datetime
    
    @validator('sample_date', pre=True)
    def parse_sample_date(cls, v):
        """Parse sample_date from various string formats"""
        if v is None:
            return None
        
        if isinstance(v, datetime):
            return v
        
        if isinstance(v, str):
            for fmt in ["%m/%d/%Y", "%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d"]:
                try:
                    return datetime.strptime(v, fmt)
                except ValueError:
                    continue
            return datetime.utcnow()
        
        return v
    
    class Config:
        json_schema_extra = {
            "example": {
                "report_id": "WQR-2024-001",
                "extracted_parameters": {
                    "pH": {"value": 7.8, "unit": None},
                    "Calcium": {"value": 85.5, "unit": "mg/L"}
                },
                "total_score": {
                    "overall_score": 85.0,
                    "rating": "Good"
                },
                "water_indices": {
                    "lsi": {"lsi": -0.3, "interpretation": "Corrosive"}
                }
            }
        }


# ========================================
# 🆕 NEW: API REQUEST MODELS
# ========================================

class CalculateIndicesRequest(BaseModel):
    """Request to calculate water chemistry indices"""
    report_id: str
    
    class Config:
        json_schema_extra = {
            "example": {
                "report_id": "WQR-2024-001"
            }
        }


class CoolingTowerRequest(BaseModel):
    """Request for cooling tower water balance"""
    recirculation_rate_gpm: float
    hot_water_temp_f: float
    cold_water_temp_f: float
    wet_bulb_temp_f: float
    coc: float
    drift_percent: Optional[float] = 0.1
    evaporation_factor_percent: Optional[float] = 85.0
    
    class Config:
        json_schema_extra = {
            "example": {
                "recirculation_rate_gpm": 10000,
                "hot_water_temp_f": 95,
                "cold_water_temp_f": 85,
                "wet_bulb_temp_f": 78,
                "coc": 4.0
            }
        }


class BatchSaturationRequest(BaseModel):
    """Request for batch saturation analysis"""
    base_water_parameters: Dict[str, Any]
    ph_range: List[float] = Field(min_items=2, max_items=2)
    coc_range: List[float] = Field(min_items=2, max_items=2)
    temp_range: List[float] = Field(min_items=2, max_items=2)
    grid_resolution: Optional[int] = 3  # Points per axis (3x3x3 = 27 total points)
    
    class Config:
        json_schema_extra = {
            "example": {
                "base_water_parameters": {
                    "pH": {"value": 7.5},
                    "Calcium": {"value": 100, "unit": "mg/L"},
                    "Alkalinity": {"value": 150, "unit": "mg/L"}
                },
                "ph_range": [6.5, 8.5],
                "coc_range": [2.0, 5.0],
                "temp_range": [25, 35],
                "grid_resolution": 3
            }
        }


class CorrosionPredictionRequest(BaseModel):
    """Request for corrosion rate prediction"""
    metal_type: str  # "mild_steel", "copper", "admiralty_brass"
    parameters: Dict[str, Any]
    saturation_indices: Dict[str, float]
    do_ppm: Optional[float] = None
    temp_c: Optional[float] = 25.0
    
    class Config:
        json_schema_extra = {
            "example": {
                "metal_type": "mild_steel",
                "parameters": {
                    "pH": {"value": 7.8},
                    "PMA": {"value": 22, "unit": "ppm"}
                },
                "saturation_indices": {
                    "Calcite": 0.3,
                    "AluminiumSilicate": 0.2
                },
                "do_ppm": 5.0,
                "temp_c": 30.0
            }
        }


# ========== EXISTING API REQUESTS (UNCHANGED) ==========

class AnalyzeRequest(BaseModel):
    """Request for water analysis (file uploaded separately)"""
    sample_location:    Optional[str]      = None
    sample_date:        Optional[datetime] = None
    analysis_date:      Optional[datetime] = None   # date lab ran the analysis
    custom_standards:   Optional[List[str]] = None

    # Water source classification
    water_use_type:     Optional[str]      = None   # "makeup_water" | "cooling_tower_water" | "process_water"
    water_source_type:  Optional[str]      = None   # "city" | "surface" | "well" | "sea"

    # Location for compliance standard
    location:           Optional[str]      = None   # "US" | "EU" | "AU" | "WHO"

    # Report metadata
    report_name:        Optional[str]      = None
    customer_id:        Optional[str]      = None
    customer_name:      Optional[str]      = None
    asset_id:           Optional[str]      = None


# class RecalculateRequest(BaseModel):
#     """Request to recalculate with adjusted parameters"""
#     report_id: str
#     adjusted_parameters: Dict[str, float]
    
#     class Config:
#         json_schema_extra = {
#             "example": {
#                 "report_id": "WQR-2024-001",
#                 "adjusted_parameters": {
#                     "Calcium": 90.0,
#                     "Magnesium": 45.0
#                 }
#             }
#         }


# ========== EXISTING API REQUESTS ==========

class AdjustedParameter(BaseModel):          # 🆕 নতুন class যোগ করুন
    name: str
    value: float


class RecalculateRequest(BaseModel):
    """Request to recalculate with adjusted parameters"""
    report_id: str
    adjusted_parameters: List[AdjustedParameter]  # ✅ Dict → List

    class Config:
        json_schema_extra = {
            "example": {
                "report_id": "WQR-2024-001",
                "adjusted_parameters": [
                    {"name": "pH", "value": 7.41},
                    {"name": "Nitrate_as_Nitrogen", "value": 0.5}
                ]
            }
        }



# ========== REPORT HISTORY (UNCHANGED) ==========

class ReportSummary(BaseModel):
    """Summary for report history list"""
    report_id: str
    sample_location: Optional[str]
    sample_date: Optional[datetime]
    created_at: datetime
    overall_score: float
    wqi_rating: str


class ReportHistoryResponse(BaseModel):
    """Report history response"""
    reports: List[ReportSummary]
    total_count: int
    page: int
    page_size: int


# ========== ERROR RESPONSES (UNCHANGED) ==========

class ErrorResponse(BaseModel):
    """Standard error response"""
    error: str
    detail: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)


# ========== PARAMETER STANDARD (Admin) ==========

class ParameterStandard(BaseModel):
    """Parameter threshold standard"""
    parameter_name: str
    unit: Optional[str] = None
    thresholds: Dict[str, Dict[str, float]]
    standards: Optional[Dict[str, Dict[str, float]]] = None
    description: Optional[str] = None
    health_impact: Optional[Dict[str, str]] = None


# ========== CALCULATION FORMULA (Admin) ==========

class CalculationFormula(BaseModel):
    """Calculation formula definition"""
    formula_name: str
    formula_type: str
    required_parameters: List[str]
    formula_expression: str
    interpretation: Optional[Dict[str, Any]] = None
    unit: Optional[str] = None
    description: Optional[str] = None


# ========================================
# ========================================
# 🆕 SATURATION ANALYSIS — New AI-server payload format
# ========================================

class RawMaterialItem(BaseModel):
    rawId:           str
    percentage:      float
    nameSnapshot:    Optional[str] = None
    costSnapshot:    Optional[float] = None


class ProductBlend(BaseModel):
    productId:        Optional[str]  = None
    productName:      Optional[str]  = None
    waterPercentage:  Optional[float] = None
    rawMaterials:     Optional[List[RawMaterialItem]] = None


class InhibitionFormula(BaseModel):
    salToInhibit:                    Optional[str] = None
    applicableIonicStrength:         Optional[str] = None
    formulaForInhibitionPerformance: Optional[str] = None


class RawMaterialChemistry(BaseModel):
    rawMaterialId:              Optional[str]  = None
    commonName:                 Optional[str]  = None
    activeComponentName:        Optional[str]  = None
    activePercentage:           Optional[float] = None
    activePercentageChemicalFormula: Optional[str] = None
    inhibitionFormulas:         Optional[List[InhibitionFormula]] = None
    bandUpperCushion:           Optional[str]  = None   # upper yellow threshold
    bandLowerCushion:           Optional[str]  = None   # lower yellow threshold


class AssetInfo(BaseModel):
    name:                   Optional[str]       = None
    type:                   Optional[str]       = None
    towerType:              Optional[str]       = None
    fillType:               Optional[str]       = None   # Film Fill High-Efficiency | Splash Fill | etc.
    draftType:              Optional[str]       = None   # Forced Draft | Induced Draft | Natural Draft
    approachToWB:           Optional[float]     = None   # cold supply temp - wet bulb temp (°F)
    systemVolume:           Optional[float]     = None
    systemMetallurgy:       Optional[List[str]] = None
    systemMaterials:        Optional[List[str]] = None
    recirculationRate:      Optional[float]     = None
    supplyTemperature:      Optional[float]     = None   # cold basin temp
    supplyTemperatureType:  Optional[str]       = None   # "°F" or "°C"
    returnTemperature:      Optional[float]     = None   # hot evaluation temp
    returnTemperatureType:  Optional[str]       = None   # "°F" or "°C"


class SaturationRunRequest(BaseModel):
    """
    Request body sent by AI server to POST /saturation/run-analysis.
    base_water_parameters is fully dynamic (OCR-extracted keys vary per report).
    All fields except base_water_parameters are optional with sensible defaults.
    """
    # Dynamic water params — keys vary (e.g. "Calcium", "Ca", "Sulphate", "SO4")
    base_water_parameters: Dict[str, Any]

    # Salt selection — null = analyze ALL available salts
    salt_id:              Optional[str]       = None
    salts_of_interest:    Optional[List[str]] = None

    # Dosage
    dosage_ppm:           Optional[float]     = 2.0

    # CoC range
    coc_min:              Optional[float]     = 1.0
    coc_max:              Optional[float]     = 10.0
    coc_interval:         Optional[float]     = 1.0

    # Temperature range
    temp_min:             Optional[float]     = 25.0
    temp_max:             Optional[float]     = 60.0
    temp_interval:        Optional[float]     = 5.0
    temp_unit:            Optional[str]       = "F"   # "F" or "C"

    # pH
    ph_mode:              Optional[str]       = "natural"  # "fixed" | "natural"
    fixed_ph:             Optional[float]     = None

    # pH adjustment chemical
    adjustment_chemical:  Optional[str]       = None   # "H2SO4" | "HCl" | "NaOH"

    # CO2 partial pressure override (auto-calculated from tower type if not provided)
    co2_log_partial_pressure: Optional[float] = None   # e.g. -3.1 for crossflow+splash fill

    # Charge balance ions
    balance_cation:       Optional[str]       = "Na"
    balance_anion:        Optional[str]       = "Cl"

    # Treatment / product info (for color band thresholds)
    product_blend:        Optional[ProductBlend]        = None
    raw_material_chemistry: Optional[RawMaterialChemistry] = None

    # Asset metadata (informational only)
    asset_info:           Optional[AssetInfo] = None

    # Location for compliance standard selection (e.g. "US", "EU", "AU", "WHO")
    location:             Optional[str]       = None

    # Report metadata
    report_name:          Optional[str]       = None   # e.g. "Q1 2026 Tower A Analysis"
    customer_id:          Optional[str]       = None
    customer_name:        Optional[str]       = None
    asset_id:             Optional[str]       = None


class SaturationSwitchSaltRequest(BaseModel):
    """Request body for POST /saturation/switch-salt"""
    run_id:    str
    salt_id:   str


# ── Response models ──────────────────────────────────────────────────────────

class SaturationIndexDetail(BaseModel):
    """Full PHREEQC saturation index detail for one mineral"""
    SI:              float
    log_IAP:         Optional[float] = None
    log_K:           Optional[float] = None
    phase:           Optional[str]   = None
    chemical_formula: Optional[str]  = None


class SaturationGridPoint(BaseModel):
    """Single grid point result"""
    _grid_CoC:               float
    _grid_temp:              float   # always Celsius
    _grid_pH:                float
    # full detail per mineral
    saturation_indices:      Dict[str, SaturationIndexDetail]
    # description of solution from PHREEQC
    description_of_solution: Optional[Dict[str, Any]] = None
    color_code:              str     # "green" | "yellow" | "red"
    ionic_strength:          Optional[float] = None
    charge_balance_error_pct: Optional[float] = None


class SaturationRunResponse(BaseModel):
    """Response from POST /saturation/run-analysis"""
    run_id:            str
    salt_id:           Optional[str]
    salts_of_interest: Optional[List[str]]
    dosage_ppm:        float
    coc_min:           float
    coc_max:           float
    coc_interval:      float
    temp_min:          float
    temp_max:          float
    temp_interval:     float
    temp_unit:         str
    ph_mode:           str
    fixed_ph:          Optional[float]
    adjustment_chemical: Optional[str]
    balance_cation:    str
    balance_anion:     str
    database_used:     str
    total_grid_points: int
    grid_results:      List[Dict[str, Any]]
    chart_data:        Dict[str, Any]   # frontend builds interactive 3D chart from this
    summary:           Dict[str, int]
    created_at:        str


class SaturationSwitchSaltResponse(BaseModel):
    run_id:     str
    salt_id:    str
    chart_data: Dict[str, Any]
    summary:    Dict[str, int]