
# """
# Water Analysis API Routes - FIXED VERSION
# ✅ Better error handling
# ✅ File validation
# ✅ Proper response formatting
# ✅ Memory management
# """

# from fastapi import APIRouter, UploadFile, File, HTTPException, Query, Body
# from typing import Optional, Dict, Any
# import logging
# from datetime import datetime

# from app.models.schemas import (
#     WaterAnalysisResponse,
#     GraphModifyRequest,
#     RecalculateRequest,
#     ReportHistoryResponse,
#     ErrorResponse
# )
# from app.services.ocr_service import OCRService
# from app.services.phreeqc_service import PHREEQCService
# from app.services.graph_service import GraphService
# from app.services.scoring_service import ScoringService
# from app.services.quality_report_service import QualityReportService
# from app.services.composition_service import CompositionService
# from app.services.biological_service import BiologicalService
# from app.services.compliance_service import ComplianceService
# from app.services.risk_analysis_service import RiskAnalysisService
# from app.services.report_history_service import ReportHistoryService
# from app.db.mongo import db

# logger = logging.getLogger(__name__)

# router = APIRouter()


# # ========================================
# # ALLOWED FILE TYPES
# # ========================================
# ALLOWED_TYPES = {
#     "application/pdf": "PDF",
#     "image/jpeg": "JPEG",
#     "image/jpg": "JPG",
#     "image/png": "PNG",
#     "image/tiff": "TIFF",
#     "image/tif": "TIF"
# }

# MAX_FILE_SIZE_MB = 50


# # ========================================
# # HELPER: VALIDATE FILE
# # ========================================
# def validate_upload_file(file: UploadFile) -> tuple[bytes, float, str]:
#     """
#     Validate uploaded file
    
#     Returns:
#         (file_content, size_mb, file_type)
    
#     Raises:
#         HTTPException if invalid
#     """
#     # Check content type
#     if file.content_type not in ALLOWED_TYPES:
#         raise HTTPException(
#             status_code=400,
#             detail=f"Unsupported file type: {file.content_type}. Allowed: {', '.join(ALLOWED_TYPES.values())}"
#         )
    
#     # Check file extension
#     if not file.filename:
#         raise HTTPException(status_code=400, detail="No filename provided")
    
#     ext = file.filename.lower().split('.')[-1]
#     if ext not in ['pdf', 'jpg', 'jpeg', 'png', 'tiff', 'tif']:
#         raise HTTPException(
#             status_code=400,
#             detail=f"Invalid file extension: .{ext}"
#         )
    
#     return (file.content_type, ALLOWED_TYPES[file.content_type])


# async def read_and_validate_file(file: UploadFile) -> tuple[bytes, float]:
#     """
#     Read and validate file size
    
#     Returns:
#         (file_content, size_mb)
#     """
#     try:
#         file_content = await file.read()
#     except Exception as e:
#         logger.error(f"Failed to read file: {e}")
#         raise HTTPException(status_code=400, detail="Failed to read file")
    
#     if not file_content:
#         raise HTTPException(status_code=400, detail="Empty file")
    
#     file_size_mb = len(file_content) / (1024 * 1024)
    
#     if file_size_mb > MAX_FILE_SIZE_MB:
#         raise HTTPException(
#             status_code=413,
#             detail=f"File too large: {file_size_mb:.2f}MB (max: {MAX_FILE_SIZE_MB}MB)"
#         )
    
#     logger.info(f"File size: {file_size_mb:.2f}MB")
    
#     return (file_content, file_size_mb)


# # ========================================
# # HELPER: ENSURE UNITS
# # ========================================
# def ensure_parameter_units(parameters: Dict[str, Any]) -> Dict[str, Any]:
#     """Ensure all parameters have unit field (even if empty string)"""
#     for param_name, param_data in parameters.items():
#         if isinstance(param_data, dict):
#             if "unit" not in param_data or param_data["unit"] is None:
#                 param_data["unit"] = ""
#     return parameters


# # ========================================
# # ENDPOINT 1: EXTRACT ONLY - FIXED
# # ========================================
# @router.post("/water/extract")
# async def extract_parameters_only(
#     file: UploadFile = File(...),
#     sample_location: Optional[str] = Query(None),
#     sample_date: Optional[str] = Query(None)
# ):
#     """
#     **STEP 1: Extract parameters from PDF/Image ONLY**
    
#     - NO calculations
#     - NO PHREEQC
#     - NO graphs
#     - ONLY raw extracted data with validation
    
#     **Use this to verify extraction before running expensive calculations**
#     """
#     ocr_service = None
    
#     try:
#         logger.info(f"📄 Starting extraction: {file.filename}")
        
#         # Validate file type
#         content_type, file_type = validate_upload_file(file)
        
#         # Read and validate size
#         file_content, file_size_mb = await read_and_validate_file(file)
        
#         logger.info(f"✅ File validated: {file.filename} ({file_type}, {file_size_mb:.2f}MB)")
        
#         # Initialize OCR service
#         try:
#             ocr_service = OCRService()
#         except Exception as e:
#             logger.error(f"Failed to initialize OCR service: {e}")
#             raise HTTPException(
#                 status_code=500,
#                 detail="OCR service initialization failed. Check OPENAI_API_KEY."
#             )
        
#         # Extract parameters
#         logger.info(f"🔍 Extracting from {file_type}...")
        
#         try:
#             extracted_data = await ocr_service.extract_from_file(
#                 file_content,
#                 file.filename,
#                 content_type
#             )
#         except Exception as e:
#             logger.error(f"Extraction failed: {e}")
#             raise HTTPException(
#                 status_code=500,
#                 detail=f"Extraction failed: {str(e)}"
#             )
        
#         # Validate extraction result
#         if not extracted_data:
#             raise HTTPException(
#                 status_code=500,
#                 detail="Extraction returned no data"
#             )
        
#         if not extracted_data.get("parameters"):
#             raise HTTPException(
#                 status_code=400,
#                 detail="No parameters extracted from file"
#             )
        
#         parameters = extracted_data["parameters"]
        
#         # Ensure units
#         parameters = ensure_parameter_units(parameters)
        
#         logger.info(f"✅ Successfully extracted {len(parameters)} parameters")
        
#         # Build response
#         response = {
#             "success": True,
#             "message": f"Successfully extracted {len(parameters)} parameters",
#             "file_info": {
#                 "filename": file.filename,
#                 "type": file_type,
#                 "size_mb": round(file_size_mb, 2),
#                 "content_type": content_type
#             },
#             "parameters": parameters,
#             "metadata": extracted_data.get("metadata", {}),
#             "validation": extracted_data.get("validation", {}),
#             "extracted_at": extracted_data.get("created_at", datetime.utcnow()).isoformat() if isinstance(extracted_data.get("created_at"), datetime) else extracted_data.get("created_at")
#         }
        
#         return response
        
#     except HTTPException:
#         raise
        
#     except Exception as e:
#         logger.exception("❌ Extraction endpoint failed")
#         raise HTTPException(
#             status_code=500,
#             detail=f"Unexpected error: {str(e)}"
#         )
    
#     finally:
#         # Cleanup
#         if ocr_service:
#             del ocr_service


# # ========================================
# # ENDPOINT 2: ANALYZE DATA - FIXED
# # ========================================
# @router.post("/water/analyze-data", response_model=WaterAnalysisResponse)
# async def analyze_extracted_data(
#     data: Dict[str, Any] = Body(...)
# ):
#     """
#     **STEP 2: Analyze already-extracted parameters**
    
#     Input format:
# ```json
#     {
#       "parameters": {
#         "pH": {"value": 7.2, "unit": ""},
#         "Calcium": {"value": 9.5, "unit": "mg/L"}
#       },
#       "sample_location": "Lab A",
#       "sample_date": "2026-01-29"
#     }
# ```
    
#     Runs: PHREEQC, graphs, scoring, compliance, risk, report
#     """
#     try:
#         logger.info("⚗️ Starting data analysis")
        
#         # Extract from request body
#         parameters = data.get("parameters", {})
#         sample_location = data.get("sample_location")
#         sample_date = data.get("sample_date")
        
#         # Validate parameters
#         if not parameters or not isinstance(parameters, dict):
#             raise HTTPException(
#                 status_code=400,
#                 detail="No valid parameters provided"
#             )
        
#         if len(parameters) == 0:
#             raise HTTPException(
#                 status_code=400,
#                 detail="Parameters dictionary is empty"
#             )
        
#         logger.info(f"⚗️ Analyzing {len(parameters)} parameters")
        
#         # Ensure units
#         parameters = ensure_parameter_units(parameters)
        
#         # PHREEQC Analysis
#         logger.info("⚗️ Running PHREEQC analysis...")
#         phreeqc_service = PHREEQCService()
#         try:
#             chemical_status = await phreeqc_service.analyze(parameters)
#         except Exception as e:
#             logger.error(f"PHREEQC analysis failed: {e}")
#             raise HTTPException(
#                 status_code=500,
#                 detail=f"Chemical analysis failed: {str(e)}"
#             )
        
#         # Graph Generation
#         logger.info("📊 Generating parameter graph...")
#         graph_service = GraphService()
#         try:
#             parameter_graph = await graph_service.create_parameter_graph(parameters, chemical_status)
#         except Exception as e:
#             logger.warning(f"Graph generation failed: {e}")
#             parameter_graph = {"error": "Graph generation failed"}
        
#         # Composition Analysis
#         logger.info("🧪 Analyzing chemical composition...")
#         composition_service = CompositionService()
#         try:
#             chemical_composition = await composition_service.analyze(parameters, chemical_status)
#         except Exception as e:
#             logger.error(f"Composition analysis failed: {e}")
#             chemical_composition = {}
        
#         # Biological Analysis
#         logger.info("🦠 Analyzing biological indicators...")
#         biological_service = BiologicalService()
#         try:
#             biological_indicators = await biological_service.analyze(parameters)
#         except Exception as e:
#             logger.warning(f"Biological analysis failed: {e}")
#             biological_indicators = {}
        
#         # Compliance Check
#         logger.info("✓ Checking compliance...")
#         compliance_service = ComplianceService()
#         try:
#             compliance_checklist = await compliance_service.check_compliance(parameters, chemical_status)
#         except Exception as e:
#             logger.error(f"Compliance check failed: {e}")
#             compliance_checklist = {}
        
#         # Risk Analysis
#         logger.info("⚠️ Analyzing contamination risks...")
#         risk_service = RiskAnalysisService()
#         try:
#             contamination_risk = await risk_service.analyze_risks(parameters, chemical_status)
#         except Exception as e:
#             logger.warning(f"Risk analysis failed: {e}")
#             contamination_risk = {}
        
#         # Calculate Total Score
#         logger.info("🎯 Calculating total score...")
#         scoring_service = ScoringService()
#         try:
#             total_score = await scoring_service.calculate_total_score(
#                 chemical_composition, biological_indicators, compliance_checklist, contamination_risk
#             )
#         except Exception as e:
#             logger.error(f"Score calculation failed: {e}")
#             total_score = {"overall_score": 0, "error": str(e)}
        
#         # Generate Quality Report
#         logger.info("📋 Generating quality report...")
#         quality_service = QualityReportService()
#         try:
#             quality_report = await quality_service.generate_report(
#                 parameters, chemical_status, compliance_checklist, contamination_risk
#             )
#         except Exception as e:
#             logger.error(f"Report generation failed: {e}")
#             quality_report = {"error": str(e)}
        
#         # Save to Database
#         logger.info("💾 Saving report to database...")
#         history_service = ReportHistoryService()
#         try:
#             report_id = await history_service.save_report(
#                 extracted_parameters=parameters,
#                 chemical_status=chemical_status,
#                 parameter_graph=parameter_graph,
#                 total_score=total_score,
#                 quality_report=quality_report,
#                 chemical_composition=chemical_composition,
#                 biological_indicators=biological_indicators,
#                 compliance_checklist=compliance_checklist,
#                 contamination_risk=contamination_risk,
#                 sample_location=sample_location,
#                 sample_date=sample_date,
#                 original_filename="manual_analysis"
#             )
            
#             logger.info(f"✅ Analysis complete! Report ID: {report_id}")
            
#         except Exception as e:
#             logger.error(f"Failed to save report: {e}")
#             report_id = "unsaved"
        
#         # Build response
#         return WaterAnalysisResponse(
#             report_id=report_id,
#             extracted_parameters=parameters,
#             parameter_graph=parameter_graph,
#             chemical_status=chemical_status,
#             total_score=total_score,
#             quality_report=quality_report,
#             chemical_composition=chemical_composition,
#             biological_indicators=biological_indicators,
#             compliance_checklist=compliance_checklist,
#             contamination_risk=contamination_risk,
#             sample_location=sample_location,
#             sample_date=sample_date,
#             created_at=datetime.utcnow()
#         )
        
#     except HTTPException:
#         raise
        
#     except Exception as e:
#         logger.exception("❌ Analysis failed")
#         raise HTTPException(
#             status_code=500,
#             detail=f"Analysis failed: {str(e)}"
#         )


# # ========================================
# # ENDPOINT 3: FULL ANALYSIS - FIXED
# # ========================================
# @router.post("/water/analyze", response_model=WaterAnalysisResponse)
# async def analyze_water_sample(
#     file: UploadFile = File(...),
#     sample_location: Optional[str] = Query(None),
#     sample_date: Optional[str] = Query(None)
# ):
#     """
#     **COMBINED: Extract + Analyze in one step**
    
#     For quick testing. For production:
#     1. Use /water/extract first
#     2. Then /water/analyze-data
#     """
#     ocr_service = None
    
#     try:
#         logger.info(f"📄 Starting full analysis: {file.filename}")
        
#         # Validate file
#         content_type, file_type = validate_upload_file(file)
#         file_content, file_size_mb = await read_and_validate_file(file)
        
#         logger.info(f"✅ File validated: {file_type}, {file_size_mb:.2f}MB")
        
#         # Extract parameters
#         logger.info("🔍 Extracting parameters...")
#         ocr_service = OCRService()
        
#         extracted_data = await ocr_service.extract_from_file(
#             file_content,
#             file.filename,
#             content_type
#         )
        
#         if not extracted_data or not extracted_data.get("parameters"):
#             raise HTTPException(
#                 status_code=400,
#                 detail="Failed to extract parameters from file"
#             )
        
#         parameters = extracted_data["parameters"]
#         parameters = ensure_parameter_units(parameters)
        
#         logger.info(f"✅ Extracted {len(parameters)} parameters")
        
#         # Run all analyses (same as analyze-data endpoint)
#         logger.info("⚗️ Running PHREEQC...")
#         phreeqc_service = PHREEQCService()
#         chemical_status = await phreeqc_service.analyze(parameters)
        
#         logger.info("📊 Generating graph...")
#         graph_service = GraphService()
#         parameter_graph = await graph_service.create_parameter_graph(parameters, chemical_status)
        
#         logger.info("🧪 Analyzing composition...")
#         composition_service = CompositionService()
#         chemical_composition = await composition_service.analyze(parameters, chemical_status)
        
#         logger.info("🦠 Biological analysis...")
#         biological_service = BiologicalService()
#         biological_indicators = await biological_service.analyze(parameters)
        
#         logger.info("✓ Compliance check...")
#         compliance_service = ComplianceService()
#         compliance_checklist = await compliance_service.check_compliance(parameters, chemical_status)
        
#         logger.info("⚠️ Risk analysis...")
#         risk_service = RiskAnalysisService()
#         contamination_risk = await risk_service.analyze_risks(parameters, chemical_status)
        
#         logger.info("🎯 Calculating score...")
#         scoring_service = ScoringService()
#         total_score = await scoring_service.calculate_total_score(
#             chemical_composition, biological_indicators, compliance_checklist, contamination_risk
#         )
        
#         logger.info("📋 Generating report...")
#         quality_service = QualityReportService()
#         quality_report = await quality_service.generate_report(
#             parameters, chemical_status, compliance_checklist, contamination_risk
#         )
        
#         logger.info("💾 Saving...")
#         history_service = ReportHistoryService()
#         report_id = await history_service.save_report(
#             extracted_parameters=parameters,
#             chemical_status=chemical_status,
#             parameter_graph=parameter_graph,
#             total_score=total_score,
#             quality_report=quality_report,
#             chemical_composition=chemical_composition,
#             biological_indicators=biological_indicators,
#             compliance_checklist=compliance_checklist,
#             contamination_risk=contamination_risk,
#             sample_location=sample_location,
#             sample_date=sample_date,
#             original_filename=file.filename
#         )
        
#         logger.info(f"✅ Complete! Report: {report_id}")
        
#         return WaterAnalysisResponse(
#             report_id=report_id,
#             extracted_parameters=parameters,
#             parameter_graph=parameter_graph,
#             chemical_status=chemical_status,
#             total_score=total_score,
#             quality_report=quality_report,
#             chemical_composition=chemical_composition,
#             biological_indicators=biological_indicators,
#             compliance_checklist=compliance_checklist,
#             contamination_risk=contamination_risk,
#             sample_location=sample_location,
#             sample_date=sample_date,
#             created_at=datetime.utcnow()
#         )
        
#     except HTTPException:
#         raise
        
#     except Exception as e:
#         logger.exception("❌ Full analysis failed")
#         raise HTTPException(
#             status_code=500,
#             detail=f"Analysis failed: {str(e)}"
#         )
    
#     finally:
#         if ocr_service:
#             del ocr_service


# # ========================================
# # OTHER ENDPOINTS (UNCHANGED)
# # ========================================

# @router.post("/water/graph/modify")
# async def modify_graph_with_prompt(request: GraphModifyRequest):
#     """Modify graph colors with prompt"""
#     try:
#         report = await db.get_water_report(request.report_id)
#         if not report:
#             raise HTTPException(status_code=404, detail="Report not found")
        
#         graph_service = GraphService()
#         updated_graph = await graph_service.modify_with_prompt(
#             request.report_id,
#             report["extracted_parameters"],
#             request.prompt
#         )
        
#         await db.update_water_report(request.report_id, {"parameter_graph": updated_graph})
        
#         return {
#             "report_id": request.report_id,
#             "updated_graph": updated_graph,
#             "prompt": request.prompt
#         }
        
#     except HTTPException:
#         raise
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=str(e))


# @router.post("/water/recalculate")
# async def recalculate_analysis(request: RecalculateRequest):
#     """Recalculate with adjusted parameters"""
#     try:
#         report = await db.get_water_report(request.report_id)
#         if not report:
#             raise HTTPException(status_code=404, detail="Report not found")
        
#         updated_parameters = {**report["extracted_parameters"]}
#         for param, value in request.adjusted_parameters.items():
#             if param in updated_parameters:
#                 updated_parameters[param]["value"] = value
        
#         phreeqc_service = PHREEQCService()
#         chemical_status = await phreeqc_service.analyze(updated_parameters)
        
#         return {
#             "report_id": request.report_id,
#             "status": "recalculated",
#             "adjusted": request.adjusted_parameters
#         }
        
#     except HTTPException:
#         raise
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=str(e))


# @router.get("/water/reports", response_model=ReportHistoryResponse)
# async def get_report_history(
#     page: int = Query(1, ge=1),
#     page_size: int = Query(20, ge=1, le=100)
# ):
#     """Get paginated report history"""
#     try:
#         skip = (page - 1) * page_size
#         reports = await db.get_all_reports(limit=page_size, skip=skip)
#         total_count = await db.db.water_ai_reports.count_documents({})
        
#         summaries = [
#             {
#                 "report_id": r["report_id"],
#                 "sample_location": r.get("sample_location"),
#                 "sample_date": r.get("sample_date"),
#                 "created_at": r["created_at"],
#                 "overall_score": r["total_score"]["overall_score"],
#                 "wqi_rating": r["quality_report"]["water_quality_index"]["rating"]
#             }
#             for r in reports
#         ]
        
#         return ReportHistoryResponse(
#             reports=summaries,
#             total_count=total_count,
#             page=page,
#             page_size=page_size
#         )
        
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=str(e))


# @router.get("/water/reports/{report_id}")
# async def get_report_by_id(report_id: str):
#     """Get specific report"""
#     try:
#         report = await db.get_water_report(report_id)
#         if not report:
#             raise HTTPException(status_code=404, detail="Report not found")
#         return report
#     except HTTPException:
#         raise
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=str(e))


# @router.delete("/water/reports/{report_id}")
# async def delete_report(report_id: str):
#     """Delete report"""
#     try:
#         deleted = await db.delete_water_report(report_id)
#         if not deleted:
#             raise HTTPException(status_code=404, detail="Report not found")
#         return {"status": "deleted", "report_id": report_id}
#     except HTTPException:
#         raise
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=str(e))


"""
Water Analysis API Routes - FIXED VERSION
✅ Better error handling
✅ File validation
✅ Proper response formatting
✅ Memory management
✅ PHREEQC result transformation (FIXED)
"""

from fastapi import APIRouter, UploadFile, File, HTTPException, Query, Body
from typing import Optional, Dict, Any
import logging
from datetime import datetime

from app.models.schemas import (
    WaterAnalysisResponse,
    GraphModifyRequest,
    RecalculateRequest,
    AdjustedParameter,
    ReportHistoryResponse,
    ErrorResponse
)
from app.services.ocr_service import OCRService
from app.services.calculation_service import CalculationService
from app.services.cooling_tower_service import CoolingTowerService
from app.services.phreeqc_service import PHREEQCService
from app.services.graph_service import GraphService
from app.services.scoring_service import ScoringService
from app.services.quality_report_service import QualityReportService
from app.services.composition_service import CompositionService
from app.services.biological_service import BiologicalService
from app.services.compliance_service import ComplianceService
from app.services.risk_analysis_service import RiskAnalysisService
from app.services.report_history_service import ReportHistoryService
from app.db.mongo import db

logger = logging.getLogger(__name__)

router = APIRouter()


# ========================================
# ALLOWED FILE TYPES
# ========================================
ALLOWED_TYPES = {
    "application/pdf": "PDF",
    "image/jpeg": "JPEG",
    "image/jpg": "JPG",
    "image/png": "PNG",
    "image/tiff": "TIFF",
    "image/tif": "TIF"
}

MAX_FILE_SIZE_MB = 50


# ========================================
# HELPER: TRANSFORM PHREEQC RESULT (✅ NEW)
# ========================================
def transform_phreeqc_result(
    phreeqc_result: Dict[str, Any],
    parameters: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Transform PHREEQC service result to API-expected format.
    
    Handles both old format (already has required fields) and new format (needs transformation).
    
    Args:
        phreeqc_result: Raw result from PHREEQC service
        parameters: Original input parameters
        
    Returns:
        Dict with all required fields for WaterAnalysisResponse
    """
    # If already has required fields, return as-is (backward compatibility)
    if "input_parameters" in phreeqc_result and "solution_parameters" in phreeqc_result:
        return phreeqc_result
    
    def get_param_value(params: Dict, key: str, default=None):
        """Safely extract parameter value from nested dict"""
        val = params.get(key)
        if val is None:
            return default
        if isinstance(val, dict):
            return val.get("value", default)
        return val
    
    def _si_status(si_val: float) -> str:
        if si_val < -0.5:  return "undersaturated"
        if si_val <= 0.5:  return "near_equilibrium"
        return "supersaturated"

    # Ensure every SI item has a status field
    raw_si = phreeqc_result.get("saturation_indices", [])
    si_with_status = []
    for item in raw_si:
        if isinstance(item, dict) and "status" not in item:
            item = {**item, "status": _si_status(item.get("si_value", 0.0))}
        si_with_status.append(item)

    # Transform to expected format
    return {
        "input_parameters": parameters,
        "solution_parameters": {
            "pH": get_param_value(parameters, "pH", 7.0),
            "temperature": get_param_value(parameters, "Temperature", 25.0),
            "ionic_strength": phreeqc_result.get("ionic_strength", 0.0),
            "pe": get_param_value(parameters, "pe"),
        },
        "charge_balance_error": phreeqc_result.get(
            "charge_balance_error",
            phreeqc_result.get("charge_balance_error_pct", 0.0)
        ),
        "saturation_indices": si_with_status,
        "ionic_strength": phreeqc_result.get("ionic_strength", 0.0),
        "database_used": phreeqc_result.get("database_used", "unknown"),
        "molalities": phreeqc_result.get("molalities", {}),
        "equilibrium_phases": phreeqc_result.get("equilibrium_phases", {}),
        "electrical_balance": phreeqc_result.get("electrical_balance", 0.0),
    }


# ========================================
# HELPER: VALIDATE FILE
# ========================================
def validate_upload_file(file: UploadFile) -> tuple[bytes, float, str]:
    """
    Validate uploaded file
    
    Returns:
        (file_content, size_mb, file_type)
    
    Raises:
        HTTPException if invalid
    """
    # Check content type
    if file.content_type not in ALLOWED_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {file.content_type}. Allowed: {', '.join(ALLOWED_TYPES.values())}"
        )
    
    # Check file extension
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")
    
    ext = file.filename.lower().split('.')[-1]
    if ext not in ['pdf', 'jpg', 'jpeg', 'png', 'tiff', 'tif']:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file extension: .{ext}"
        )
    
    return (file.content_type, ALLOWED_TYPES[file.content_type])


async def read_and_validate_file(file: UploadFile) -> tuple[bytes, float]:
    """
    Read and validate file size
    
    Returns:
        (file_content, size_mb)
    """
    try:
        file_content = await file.read()
    except Exception as e:
        logger.error(f"Failed to read file: {e}")
        raise HTTPException(status_code=400, detail="Failed to read file")
    
    if not file_content:
        raise HTTPException(status_code=400, detail="Empty file")
    
    file_size_mb = len(file_content) / (1024 * 1024)
    
    if file_size_mb > MAX_FILE_SIZE_MB:
        raise HTTPException(
            status_code=413,
            detail=f"File too large: {file_size_mb:.2f}MB (max: {MAX_FILE_SIZE_MB}MB)"
        )
    
    logger.info(f"File size: {file_size_mb:.2f}MB")
    
    return (file_content, file_size_mb)


# ========================================
# HELPER: ENSURE UNITS
# ========================================
def ensure_parameter_units(parameters: Dict[str, Any]) -> Dict[str, Any]:
    """Ensure all parameters have unit field (even if empty string)"""
    for param_name, param_data in parameters.items():
        if isinstance(param_data, dict):
            if "unit" not in param_data or param_data["unit"] is None:
                param_data["unit"] = ""
    return parameters


# ========================================
# ENDPOINT 1: EXTRACT ONLY - FIXED
# ========================================
@router.post("/water/extract")
async def extract_parameters_only(
    file: UploadFile = File(...),
    sample_location: Optional[str] = Query(None),
    sample_date: Optional[str] = Query(None)
):
    """
    **STEP 1: Extract parameters from PDF/Image ONLY**
    
    - NO calculations
    - NO PHREEQC
    - NO graphs
    - ONLY raw extracted data with validation
    
    **Use this to verify extraction before running expensive calculations**
    """
    ocr_service = None
    
    try:
        logger.info(f"📄 Starting extraction: {file.filename}")
        
        # Validate file type
        content_type, file_type = validate_upload_file(file)
        
        # Read and validate size
        file_content, file_size_mb = await read_and_validate_file(file)
        
        logger.info(f"✅ File validated: {file.filename} ({file_type}, {file_size_mb:.2f}MB)")
        
        # Initialize OCR service
        try:
            ocr_service = OCRService()
        except Exception as e:
            logger.error(f"Failed to initialize OCR service: {e}")
            raise HTTPException(
                status_code=500,
                detail="OCR service initialization failed. Check OPENAI_API_KEY."
            )
        
        # Extract parameters
        logger.info(f"🔍 Extracting from {file_type}...")
        
        try:
            extracted_data = await ocr_service.extract_from_file(
                file_content,
                file.filename,
                content_type
            )
        except Exception as e:
            logger.error(f"Extraction failed: {e}")
            raise HTTPException(
                status_code=500,
                detail=f"Extraction failed: {str(e)}"
            )
        
        # Validate extraction result
        if not extracted_data:
            raise HTTPException(
                status_code=500,
                detail="Extraction returned no data"
            )
        
        if not extracted_data.get("parameters"):
            raise HTTPException(
                status_code=400,
                detail="No parameters extracted from file"
            )
        
        parameters = extracted_data["parameters"]
        
        # Ensure units
        parameters = ensure_parameter_units(parameters)
        
        logger.info(f"✅ Successfully extracted {len(parameters)} parameters")
        
        # Build response
        response = {
            "success": True,
            "message": f"Successfully extracted {len(parameters)} parameters",
            "file_info": {
                "filename": file.filename,
                "type": file_type,
                "size_mb": round(file_size_mb, 2),
                "content_type": content_type
            },
            "parameters": parameters,
            "metadata": extracted_data.get("metadata", {}),
            "validation": extracted_data.get("validation", {}),
            "extracted_at": extracted_data.get("created_at", datetime.utcnow()).isoformat() if isinstance(extracted_data.get("created_at"), datetime) else extracted_data.get("created_at")
        }
        
        return response
        
    except HTTPException:
        raise
        
    except Exception as e:
        logger.exception("❌ Extraction endpoint failed")
        raise HTTPException(
            status_code=500,
            detail=f"Unexpected error: {str(e)}"
        )
    
    finally:
        # Cleanup
        if ocr_service:
            del ocr_service


# ========================================
# ENDPOINT 2: ANALYZE DATA - FIXED
# ========================================
@router.post("/water/analyze-data", response_model=WaterAnalysisResponse)
async def analyze_extracted_data(
    data: Dict[str, Any] = Body(...)
):
    """
    **STEP 2: Analyze already-extracted parameters**
    
    Input format:
    ```json
    {
      "parameters": {
        "pH": {"value": 7.2, "unit": ""},
        "Calcium": {"value": 9.5, "unit": "mg/L"}
      },
      "sample_location": "Lab A",
      "sample_date": "2026-01-29"
    }
    ```
    
    Runs: PHREEQC, graphs, scoring, compliance, risk, report
    """
    try:
        logger.info("⚗️ Starting data analysis")
        
        # Extract from request body
        parameters      = data.get("parameters", {})
        sample_location = data.get("sample_location")
        sample_date     = data.get("sample_date")
        analysis_date   = data.get("analysis_date")
        water_use_type  = data.get("water_use_type")    # makeup_water | cooling_tower_water | process_water
        water_source_type = data.get("water_source_type")  # city | surface | well | sea
        location        = data.get("location")
        report_name     = data.get("report_name")
        customer_id     = data.get("customer_id")
        customer_name   = data.get("customer_name")
        asset_id        = data.get("asset_id")
        
        # Validate parameters
        if not parameters or not isinstance(parameters, dict):
            raise HTTPException(
                status_code=400,
                detail="No valid parameters provided"
            )
        
        if len(parameters) == 0:
            raise HTTPException(
                status_code=400,
                detail="Parameters dictionary is empty"
            )
        
        logger.info(f"⚗️ Analyzing {len(parameters)} parameters")
        
        # Ensure units
        parameters = ensure_parameter_units(parameters)
        
        # PHREEQC Analysis (✅ FIXED)
        logger.info("⚗️ Running PHREEQC analysis...")
        phreeqc_service = PHREEQCService()
        try:
            phreeqc_result = await phreeqc_service.analyze(parameters)
            chemical_status = transform_phreeqc_result(phreeqc_result, parameters)
        except Exception as e:
            logger.error(f"PHREEQC analysis failed: {e}")
            raise HTTPException(
                status_code=500,
                detail=f"Chemical analysis failed: {str(e)}"
            )
        
        # Graph Generation
        logger.info("📊 Generating parameter graph...")
        graph_service = GraphService()
        try:
            parameter_graph = await graph_service.create_parameter_graph(parameters, chemical_status)
        except Exception as e:
            logger.warning(f"Graph generation failed: {e}")
            parameter_graph = {"error": "Graph generation failed"}

        # Derived Calculations (TDS from conductivity, Ca ratios)
        logger.info("🔢 Calculating derived parameters...")
        try:
            calc_service    = CalculationService()
            derived_params  = calc_service.calculate_derived_parameters(parameters)
        except Exception as e:
            logger.warning(f"Derived calculations failed: {e}")
            derived_params  = {}
        
        # Composition Analysis
        logger.info("🧪 Analyzing chemical composition...")
        composition_service = CompositionService()
        try:
            chemical_composition = await composition_service.analyze(parameters, chemical_status)
        except Exception as e:
            logger.error(f"Composition analysis failed: {e}")
            chemical_composition = {}
        
        # Biological Analysis
        logger.info("🦠 Analyzing biological indicators...")
        biological_service = BiologicalService()
        try:
            biological_indicators = await biological_service.analyze(parameters)
        except Exception as e:
            logger.warning(f"Biological analysis failed: {e}")
            biological_indicators = {}
        
        # Compliance Check
        logger.info("✓ Checking compliance...")
        compliance_service = ComplianceService()
        try:
            compliance_checklist = await compliance_service.check_compliance(parameters, chemical_status, location=location)
        except Exception as e:
            logger.error(f"Compliance check failed: {e}")
            compliance_checklist = {}
        
        # Risk Analysis
        logger.info("⚠️ Analyzing contamination risks...")
        risk_service = RiskAnalysisService()
        try:
            contamination_risk = await risk_service.analyze_risks(parameters, chemical_status)
        except Exception as e:
            logger.warning(f"Risk analysis failed: {e}")
            contamination_risk = {}
        
        # Calculate Total Score
        logger.info("🎯 Calculating total score...")
        scoring_service = ScoringService()
        try:
            total_score = await scoring_service.calculate_total_score(
                chemical_composition, biological_indicators, compliance_checklist, contamination_risk
            )
        except Exception as e:
            logger.error(f"Score calculation failed: {e}")
            total_score = {"overall_score": 0, "error": str(e)}
        
        # Generate Quality Report
        logger.info("📋 Generating quality report...")
        quality_service = QualityReportService()
        try:
            quality_report = await quality_service.generate_report(
                parameters, chemical_status, compliance_checklist, contamination_risk
            )
        except Exception as e:
            logger.error(f"Report generation failed: {e}")
            quality_report = {"error": str(e)}
        
        # Save to Database
        logger.info("💾 Saving report to database...")
        history_service = ReportHistoryService()
        try:
            report_id = await history_service.save_report(
                extracted_parameters=parameters,
                chemical_status=chemical_status,
                parameter_graph=parameter_graph,
                total_score=total_score,
                quality_report=quality_report,
                chemical_composition=chemical_composition,
                biological_indicators=biological_indicators,
                compliance_checklist=compliance_checklist,
                contamination_risk=contamination_risk,
                sample_location=sample_location,
                sample_date=sample_date,
                original_filename="manual_analysis"
            )
            
            logger.info(f"✅ Analysis complete! Report ID: {report_id}")
            
        except Exception as e:
            logger.error(f"Failed to save report: {e}")
            report_id = "unsaved"
        
        # Build response
        return WaterAnalysisResponse(
            report_id=report_id,
            extracted_parameters=parameters,
            parameter_graph=parameter_graph,
            chemical_status=chemical_status,
            total_score=total_score,
            quality_report=quality_report,
            chemical_composition=chemical_composition,
            biological_indicators=biological_indicators,
            compliance_checklist=compliance_checklist,
            contamination_risk=contamination_risk,
            sample_location=sample_location,
            sample_date=sample_date,
            analysis_date=analysis_date,
            water_use_type=water_use_type,
            water_source_type=water_source_type,
            location=location,
            report_name=report_name,
            customer_id=customer_id,
            customer_name=customer_name,
            asset_id=asset_id,
            created_at=datetime.utcnow()
        )
        
    except HTTPException:
        raise
        
    except Exception as e:
        logger.exception("❌ Analysis failed")
        raise HTTPException(
            status_code=500,
            detail=f"Analysis failed: {str(e)}"
        )


# ========================================
# ENDPOINT 3: FULL ANALYSIS - FIXED
# ========================================
@router.post("/water/analyze", response_model=WaterAnalysisResponse)
async def analyze_water_sample(
    file: UploadFile = File(...),
    sample_location: Optional[str] = Query(None),
    sample_date: Optional[str] = Query(None)
):
    """
    **COMBINED: Extract + Analyze in one step**
    
    For quick testing. For production:
    1. Use /water/extract first
    2. Then /water/analyze-data
    """
    ocr_service = None
    
    try:
        logger.info(f"📄 Starting full analysis: {file.filename}")
        
        # Validate file
        content_type, file_type = validate_upload_file(file)
        file_content, file_size_mb = await read_and_validate_file(file)
        
        logger.info(f"✅ File validated: {file_type}, {file_size_mb:.2f}MB")
        
        # Extract parameters
        logger.info("🔍 Extracting parameters...")
        ocr_service = OCRService()
        
        extracted_data = await ocr_service.extract_from_file(
            file_content,
            file.filename,
            content_type
        )
        
        if not extracted_data or not extracted_data.get("parameters"):
            raise HTTPException(
                status_code=400,
                detail="Failed to extract parameters from file"
            )
        
        parameters = extracted_data["parameters"]
        parameters = ensure_parameter_units(parameters)
        
        logger.info(f"✅ Extracted {len(parameters)} parameters")
        
        # Run all analyses (same as analyze-data endpoint)
        
        # PHREEQC Analysis (✅ FIXED)
        logger.info("⚗️ Running PHREEQC...")
        phreeqc_service = PHREEQCService()
        phreeqc_result = await phreeqc_service.analyze(parameters)
        chemical_status = transform_phreeqc_result(phreeqc_result, parameters)
        
        logger.info("📊 Generating graph...")
        graph_service = GraphService()
        parameter_graph = await graph_service.create_parameter_graph(parameters, chemical_status)
        
        logger.info("🧪 Analyzing composition...")
        composition_service = CompositionService()
        chemical_composition = await composition_service.analyze(parameters, chemical_status)
        
        logger.info("🦠 Biological analysis...")
        biological_service = BiologicalService()
        biological_indicators = await biological_service.analyze(parameters)
        
        logger.info("✓ Compliance check...")
        compliance_service = ComplianceService()
        compliance_checklist = await compliance_service.check_compliance(parameters, chemical_status)
        
        logger.info("⚠️ Risk analysis...")
        risk_service = RiskAnalysisService()
        contamination_risk = await risk_service.analyze_risks(parameters, chemical_status)
        
        logger.info("🎯 Calculating score...")
        scoring_service = ScoringService()
        total_score = await scoring_service.calculate_total_score(
            chemical_composition, biological_indicators, compliance_checklist, contamination_risk
        )
        
        logger.info("📋 Generating report...")
        quality_service = QualityReportService()
        quality_report = await quality_service.generate_report(
            parameters, chemical_status, compliance_checklist, contamination_risk
        )
        
        logger.info("💾 Saving...")
        history_service = ReportHistoryService()
        report_id = await history_service.save_report(
            extracted_parameters=parameters,
            chemical_status=chemical_status,
            parameter_graph=parameter_graph,
            total_score=total_score,
            quality_report=quality_report,
            chemical_composition=chemical_composition,
            biological_indicators=biological_indicators,
            compliance_checklist=compliance_checklist,
            contamination_risk=contamination_risk,
            sample_location=sample_location,
            sample_date=sample_date,
            original_filename=file.filename
        )
        
        logger.info(f"✅ Complete! Report: {report_id}")
        
        return WaterAnalysisResponse(
            report_id=report_id,
            extracted_parameters=parameters,
            parameter_graph=parameter_graph,
            chemical_status=chemical_status,
            total_score=total_score,
            quality_report=quality_report,
            chemical_composition=chemical_composition,
            biological_indicators=biological_indicators,
            compliance_checklist=compliance_checklist,
            contamination_risk=contamination_risk,
            sample_location=sample_location,
            sample_date=sample_date,
            created_at=datetime.utcnow()
        )
        
    except HTTPException:
        raise
        
    except Exception as e:
        logger.exception("❌ Full analysis failed")
        raise HTTPException(
            status_code=500,
            detail=f"Analysis failed: {str(e)}"
        )
    
    finally:
        if ocr_service:
            del ocr_service


# ========================================
# OTHER ENDPOINTS (UNCHANGED)
# ========================================

@router.post("/water/graph/modify")
async def modify_graph_with_prompt(request: GraphModifyRequest):
    """Modify graph colors with prompt"""
    try:
        report = await db.get_water_report(request.report_id)
        if not report:
            raise HTTPException(status_code=404, detail="Report not found")
        
        graph_service = GraphService()
        updated_graph = await graph_service.modify_with_prompt(
            request.report_id,
            report["extracted_parameters"],
            request.prompt
        )
        
        await db.update_water_report(request.report_id, {"parameter_graph": updated_graph})
        
        return {
            "report_id": request.report_id,
            "updated_graph": updated_graph,
            "prompt": request.prompt
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# @router.post("/water/recalculate")
# async def recalculate_analysis(request: RecalculateRequest):
#     """Recalculate with adjusted parameters"""
#     try:
#         report = await db.get_water_report(request.report_id)
#         if not report:
#             raise HTTPException(status_code=404, detail="Report not found")
        
#         updated_parameters = {**report["extracted_parameters"]}
#         # for param, value in request.adjusted_parameters.items():
#         #     if param in updated_parameters:
#         #         updated_parameters[param]["value"] = value
#         for param in request.adjusted_parameters:
#              if param.name in updated_parameters:
#                   updated_parameters[param.name]["value"] = param.value
        
#         # ✅ FIXED: Transform PHREEQC result
#         phreeqc_service = PHREEQCService()
#         phreeqc_result = await phreeqc_service.analyze(updated_parameters)
#         chemical_status = transform_phreeqc_result(phreeqc_result, updated_parameters)
        
#         # return {
#         #     "report_id": request.report_id,
#         #     "status": "recalculated",
#         #     "adjusted": request.adjusted_parameters,
#         #     "chemical_status": chemical_status
#         # }
#         return {
#                 "report_id": request.report_id,
#                 "status": "recalculated",
#                 "adjusted": {p.name: p.value for p in request.adjusted_parameters},  # ✅
#                 "chemical_status": chemical_status
#            }
#     except HTTPException:
#         raise
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=str(e))



@router.post("/water/recalculate", response_model=WaterAnalysisResponse)
async def recalculate_analysis(request: RecalculateRequest):
    """Recalculate with adjusted parameters - returns full analysis"""
    try:
        report = await db.get_water_report(request.report_id)
        if not report:
            raise HTTPException(status_code=404, detail="Report not found")

        # ✅ Adjusted parameters update
        updated_parameters = {**report["extracted_parameters"]}
        for param in request.adjusted_parameters:
            if param.name in updated_parameters:
                updated_parameters[param.name]["value"] = param.value

        # ✅ PHREEQC
        phreeqc_service = PHREEQCService()
        phreeqc_result = await phreeqc_service.analyze(updated_parameters)
        chemical_status = transform_phreeqc_result(phreeqc_result, updated_parameters)

        # ✅ Graph
        graph_service = GraphService()
        parameter_graph = await graph_service.create_parameter_graph(updated_parameters, chemical_status)

        # ✅ Composition
        composition_service = CompositionService()
        chemical_composition = await composition_service.analyze(updated_parameters, chemical_status)

        # ✅ Biological
        biological_service = BiologicalService()
        biological_indicators = await biological_service.analyze(updated_parameters)

        # ✅ Compliance
        compliance_service = ComplianceService()
        compliance_checklist = await compliance_service.check_compliance(updated_parameters, chemical_status)

        # ✅ Risk
        risk_service = RiskAnalysisService()
        contamination_risk = await risk_service.analyze_risks(updated_parameters, chemical_status)

        # ✅ Score
        scoring_service = ScoringService()
        total_score = await scoring_service.calculate_total_score(
            chemical_composition, biological_indicators, compliance_checklist, contamination_risk
        )

        # ✅ Quality Report
        quality_service = QualityReportService()
        quality_report = await quality_service.generate_report(
            updated_parameters, chemical_status, compliance_checklist, contamination_risk
        )

        # ✅ Save updated report
        history_service = ReportHistoryService()
        report_id = await history_service.save_report(
            extracted_parameters=updated_parameters,
            chemical_status=chemical_status,
            parameter_graph=parameter_graph,
            total_score=total_score,
            quality_report=quality_report,
            chemical_composition=chemical_composition,
            biological_indicators=biological_indicators,
            compliance_checklist=compliance_checklist,
            contamination_risk=contamination_risk,
            sample_location=report.get("sample_location"),
            sample_date=report.get("sample_date"),
            original_filename="recalculated"
        )

        return WaterAnalysisResponse(
            report_id=report_id,
            extracted_parameters=updated_parameters,
            parameter_graph=parameter_graph,
            chemical_status=chemical_status,
            total_score=total_score,
            quality_report=quality_report,
            chemical_composition=chemical_composition,
            biological_indicators=biological_indicators,
            compliance_checklist=compliance_checklist,
            contamination_risk=contamination_risk,
            sample_location=report.get("sample_location"),
            sample_date=report.get("sample_date"),
            created_at=datetime.utcnow()
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/water/reports", response_model=ReportHistoryResponse)
async def get_report_history(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100)
):
    """Get paginated report history"""
    try:
        skip = (page - 1) * page_size
        reports = await db.get_all_reports(limit=page_size, skip=skip)
        total_count = await db.db.water_ai_reports.count_documents({})
        
        summaries = [
            {
                "report_id": r["report_id"],
                "sample_location": r.get("sample_location"),
                "sample_date": r.get("sample_date"),
                "created_at": r["created_at"],
                "overall_score": r["total_score"]["overall_score"],
                "wqi_rating": r["quality_report"]["water_quality_index"]["rating"]
            }
            for r in reports
        ]
        
        return ReportHistoryResponse(
            reports=summaries,
            total_count=total_count,
            page=page,
            page_size=page_size
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/water/reports/{report_id}")
async def get_report_by_id(report_id: str):
    """Get specific report"""
    try:
        report = await db.get_water_report(report_id)
        if not report:
            raise HTTPException(status_code=404, detail="Report not found")
        return report
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/water/reports/{report_id}")
async def delete_report(report_id: str):
    """Delete report"""
    try:
        deleted = await db.delete_water_report(report_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Report not found")
        return {"status": "deleted", "report_id": report_id}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    


# ========================================
# 1️⃣ CALCULATE INDICES - UPDATED (Report ID support)
# ========================================
@router.post("/water/calculate-indices")
async def calculate_water_indices(
    report_id: Optional[str] = Query(None),
    data: Optional[Dict[str, Any]] = Body(None)
):
    """
    Calculate water chemistry indices (LSI, Ryznar, CCPP, etc.)
    
    Option A: Use report_id (automatic from existing report)
    Option B: Provide parameters manually
    """
    try:
        calc_service = CalculationService()
        
        # Option A: From report_id
        if report_id:
            report = await db.get_water_report(report_id)
            if not report:
                raise HTTPException(status_code=404, detail="Report not found")
            
            parameters = report["extracted_parameters"]
            phreeqc_output = report["chemical_status"]
            ionic_strength = phreeqc_output.get("ionic_strength", 0.0)
        
        # Option B: Manual input
        else:
            if not data:
                raise HTTPException(
                    status_code=400,
                    detail="Either report_id or data body required"
                )
            
            parameters = data.get("parameters")
            phreeqc_output = data.get("phreeqc_output", {})
            ionic_strength = phreeqc_output.get("ionic_strength", 0.0)
            
            if not parameters:
                raise HTTPException(
                    status_code=400,
                    detail="parameters required in request body"
                )
        
        # Calculate all indices
        indices = await calc_service.calculate_all_indices(
            parameters,
            phreeqc_output,
            ionic_strength
        )
        
        # Save to database if report_id provided
        if report_id:
            await db.update_water_report(report_id, {
                "water_indices": indices
            })
        
        return {
            "success": True,
            "report_id": report_id,
            "indices": indices
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("❌ Indices calculation failed")
        raise HTTPException(status_code=500, detail=str(e))


# ========================================
# 2️⃣ COOLING TOWER - KEEP AS IS (Manual only)
# ========================================
@router.post("/water/cooling-tower")
async def calculate_cooling_tower(data: Dict[str, Any] = Body(...)):
    """
    Complete cooling tower water balance
    
    Requires manual input (tower-specific data)
    """
    try:
        tower_service = CoolingTowerService()
        
        # Extract and validate parameters
        recirc_rate = data.get("recirculation_rate_gpm")
        hot_temp = data.get("hot_water_temp_f")
        cold_temp = data.get("cold_water_temp_f")
        wet_bulb = data.get("wet_bulb_temp_f")
        coc = data.get("coc")
        drift_percent = data.get("drift_percent", 0.1)
        evap_factor = data.get("evaporation_factor_percent", 85.0)
        
        # Validation
        if not all([recirc_rate, hot_temp, cold_temp, wet_bulb, coc]):
            raise HTTPException(
                status_code=400,
                detail="Missing required parameters: recirculation_rate_gpm, hot_water_temp_f, cold_water_temp_f, wet_bulb_temp_f, coc"
            )
        
        # Calculate water balance
        balance = await tower_service.calculate_tower_water_balance(
            recirc_rate,
            hot_temp,
            cold_temp,
            wet_bulb,
            coc,
            drift_percent,
            evap_factor
        )
        
        return {
            "success": True,
            "cooling_tower_analysis": balance
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("❌ Cooling tower calculation failed")
        raise HTTPException(status_code=500, detail=str(e))


# ========================================
# 3️⃣ BATCH SATURATION - UPDATED (Report ID support)
# ========================================
@router.post("/water/batch-saturation")
async def batch_saturation_analysis(data: Dict[str, Any] = Body(...)):
    """
    Run batch saturation analysis across pH/CoC/Temp grid
    
    Option A: report_id + ranges (automatic)
    Option B: base_water_parameters + ranges (manual)
    
    Uses SOLUTION_SPREAD for efficiency
    """
    try:
        # Extract ranges (required for both options)
        ph_range = data.get("ph_range", [6.0, 9.0])
        coc_range = data.get("coc_range", [1.0, 5.0])
        temp_range = data.get("temp_range", [20.0, 40.0])
        grid_resolution = data.get("grid_resolution", 3)
        
        # Option A: From report_id
        if "report_id" in data:
            report_id = data["report_id"]
            report = await db.get_water_report(report_id)
            if not report:
                raise HTTPException(status_code=404, detail="Report not found")
            
            base_water = report["extracted_parameters"]
            logger.info(f"📊 Using base water from report: {report_id}")
        
        # Option B: Manual base_water_parameters
        else:
            base_water = data.get("base_water_parameters")
            if not base_water:
                raise HTTPException(
                    status_code=400,
                    detail="Either report_id or base_water_parameters required"
                )
            logger.info("📊 Using manually provided base water parameters")
        
        # Generate grid points
        import numpy as np
        
        ph_points = np.linspace(ph_range[0], ph_range[1], grid_resolution)
        coc_points = np.linspace(coc_range[0], coc_range[1], grid_resolution)
        temp_points = np.linspace(temp_range[0], temp_range[1], grid_resolution)
        
        grid_points = []
        for ph in ph_points:
            for coc in coc_points:
                for temp in temp_points:
                    grid_points.append({
                        "pH": float(ph),
                        "CoC": float(coc),
                        "temp": float(temp)
                    })
        
        logger.info(f"📊 Running batch analysis for {len(grid_points)} points")
        
        # PHREEQC service
        phreeqc_service = PHREEQCService()
        
        # Select database
        database = phreeqc_service.select_database(
            base_water,
            tuple(ph_range),
            tuple(coc_range),
            tuple(temp_range)
        )
        
        # Run SOLUTION_SPREAD
        results = await phreeqc_service.run_batch_solution_spread(
            base_water,
            grid_points,
            database
        )
        
        return {
            "success": True,
            "grid_points": grid_points,
            "total_points": len(grid_points),
            "results": results,
            "database_used": database
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("❌ Batch saturation failed")
        raise HTTPException(status_code=500, detail=str(e))


# ========================================
# 4️⃣ CORROSION RATE - UPDATED (Report ID support)
# ========================================
@router.post("/water/corrosion-rate")
async def predict_corrosion_rate(
    report_id: Optional[str] = Query(None),
    data: Optional[Dict[str, Any]] = Body(None)
):
    """
    Predict corrosion rate for different metals
    
    Option A: report_id + metal_type (automatic)
    Option B: Full manual input
    
    Supported metals:
    - mild_steel
    - copper
    - admiralty_brass
    """
    try:
        calc_service = CalculationService()
        
        # Option A: From report_id
        if report_id:
            report = await db.get_water_report(report_id)
            if not report:
                raise HTTPException(status_code=404, detail="Report not found")
            
            parameters = report["extracted_parameters"]
            
            # Extract saturation indices from chemical_status
            sat_indices = {}
            for si in report["chemical_status"].get("saturation_indices", []):
                sat_indices[si["mineral_name"]] = si["si_value"]
            
            # Get DO and temp from parameters
            do_ppm = CalculationService.get_param_value(parameters, "DO", 5.0)
            temp_c = CalculationService.get_param_value(parameters, "Temperature", 25.0)
            pH = CalculationService.get_param_value(parameters, "pH", 7.0)
            
            # Get metal type from data or default
            metal_type = data.get("metal_type", "mild_steel") if data else "mild_steel"
            
            logger.info(f"🔧 Using data from report: {report_id}")
        
        # Option B: Manual input
        else:
            if not data:
                raise HTTPException(
                    status_code=400,
                    detail="Either report_id or data body required"
                )
            
            parameters = data.get("parameters", {})
            sat_indices = data.get("saturation_indices", {})
            do_ppm = data.get("do_ppm", 5.0)
            temp_c = data.get("temp_c", 25.0)
            pH = data.get("pH", 7.0)
            metal_type = data.get("metal_type", "mild_steel")
            
            if not parameters:
                raise HTTPException(
                    status_code=400,
                    detail="parameters required in request body"
                )
        
        # Calculate corrosion rate based on metal type
        if metal_type == "mild_steel":
            result = await calc_service.calculate_mild_steel_corrosion(
                parameters,
                sat_indices,
                do_ppm,
                temp_c
            )
        elif metal_type == "copper":
            result = await calc_service.calculate_copper_corrosion(
                parameters,
                sat_indices,
                do_ppm,
                temp_c,
                pH
            )
        else:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported metal type: {metal_type}. Supported: mild_steel, copper"
            )
        
        # Save to database if report_id provided
        if report_id:
            await db.update_water_report(report_id, {
                f"corrosion_predictions.{metal_type}": result
            })
        
        return {
            "success": True,
            "metal_type": metal_type,
            "corrosion_prediction": result
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("❌ Corrosion prediction failed")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# SATURATION ANALYSIS — 3 Endpoints
# ============================================================
from app.services.saturation_service import SaturationService
from app.models.schemas import (
    SaturationRunRequest,
    SaturationRunResponse,
    SaturationSwitchSaltRequest,
    SaturationSwitchSaltResponse,
)


def _normalize_saturation_payload(raw: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalize two payload formats into a single flat dict for SaturationService.run_analysis().

    Format A (AI-server format):
    {
      "assetId": "...",
      "name": "...",
      "waterReportId": "...",
      "inputConfig": {
        "salt_id": "...",
        "salts_of_interest": [...],
        "dosage_ppm": 11,
        "coc_min": 1, "coc_max": 10, "coc_interval": 2,
        "temp_min": 1, "temp_max": 10, "temp_interval": 5,
        "temp_unit": "C",
        "ph_mode": "natural",
        "adjustment_chemical": "H2SO4",
        "balance_cation": "Ca",
        "balance_anion": "SO4"
      },
      "treatment": { "productId": "...", "dosage": 5 }
    }

    Format B (direct format — already flat):
    {
      "base_water_parameters": {...},
      "salt_id": "...",
      ...
    }
    """
    # If already in Format B (has base_water_parameters at top level), return as-is
    if "base_water_parameters" in raw:
        return raw

    # Format A: flatten inputConfig into top-level
    result: Dict[str, Any] = {}

    # Merge inputConfig fields to top level
    input_config = raw.get("inputConfig") or {}
    result.update(input_config)

    # base_water_parameters — may be inside inputConfig or at top level
    if "base_water_parameters" not in result:
        bwp = raw.get("base_water_parameters") or input_config.get("base_water_parameters") or {}
        result["base_water_parameters"] = bwp

    # Asset metadata
    asset_info = raw.get("asset_info") or raw.get("assetInfo") or {}
    if not asset_info and raw.get("assetId"):
        asset_info = {"assetId": raw["assetId"]}
    result["asset_info"] = asset_info

    # Treatment / product blend
    treatment = raw.get("treatment") or {}
    if treatment and "product_blend" not in result:
        result["product_blend"] = {
            "productId": treatment.get("productId"),
            "dosage":    treatment.get("dosage"),
        }
        # dosage_ppm from treatment if not in inputConfig
        if "dosage_ppm" not in result and treatment.get("dosage"):
            result["dosage_ppm"] = float(treatment["dosage"])

    # raw_material_chemistry — may be at top level
    if "raw_material_chemistry" not in result:
        result["raw_material_chemistry"] = raw.get("raw_material_chemistry") or raw.get("rawMaterialChemistry")

    # Metadata fields
    result.setdefault("asset_id",      raw.get("assetId"))
    result.setdefault("report_name",   raw.get("name") or raw.get("waterReportId"))
    result.setdefault("customer_id",   raw.get("customerId"))
    result.setdefault("customer_name", raw.get("customerName"))

    return result


@router.post(
    "/saturation/run-analysis",
    summary="Run Saturation Analysis & Generate 3D Graph",
    tags=["Saturation Analysis"],
)
async def run_saturation_analysis(raw_body: Dict[str, Any] = Body(...)):
    """
    Full saturation analysis pipeline.
    Accepts two payload formats:

    Format A (AI-server format):
      { "assetId": "...", "waterReportId": "...", "inputConfig": { "salt_id": ..., ... },
        "treatment": { "productId": ..., "dosage": ... } }

    Format B (direct format):
      { "base_water_parameters": {...}, "salt_id": ..., ... }

    salt_id / salts_of_interest = null → analyze ALL salts
    """
    try:
        service = SaturationService()

        # ── Detect and normalize payload format ──────────────────────────────
        req = _normalize_saturation_payload(raw_body)

        # ── Fetch base_water_parameters from DB if not provided ───────────────
        if not req.get("base_water_parameters"):
            water_report_id = raw_body.get("waterReportId") or raw_body.get("water_report_id")
            if water_report_id:
                # Try to fetch from water_reports collection
                report = await db.db["water_reports"].find_one(
                    {"reportId": water_report_id},
                    {"_id": 0, "parameters": 1, "waterParameters": 1, "base_water_parameters": 1}
                )
                if report:
                    bwp = (
                        report.get("base_water_parameters")
                        or report.get("waterParameters")
                        or report.get("parameters")
                        or {}
                    )
                    req["base_water_parameters"] = bwp
                    logger.info(f"Fetched base_water_parameters from waterReportId={water_report_id}: {list(bwp.keys())}")
                else:
                    logger.warning(f"waterReportId={water_report_id} not found in DB. base_water_parameters will be empty.")

        if not req.get("base_water_parameters"):
            raise ValueError(
                "base_water_parameters is required. "
                "Provide it directly in the payload or via a valid waterReportId."
            )

        result = await service.run_analysis(req)
        return {"success": True, "message": "Successfully performed Saturation Analysis!", "data": result}

    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        logger.exception("Saturation analysis unexpected error")
        raise HTTPException(status_code=500, detail=f"Unexpected error: {str(e)}")


@router.post(
    "/saturation/switch-salt",
    summary="Switch Salt View (no PHREEQC re-run)",
    tags=["Saturation Analysis"],
)
async def switch_salt_view(request: SaturationSwitchSaltRequest):
    """
    Re-generate 3D graph for a different salt using already-saved grid data.
    No PHREEQC re-calculation — instant response.

    Body: { "run_id": "...", "salt_id": "Gypsum" }
    """
    try:
        service = SaturationService()
        result  = await service.switch_salt(request.run_id, request.salt_id)
        return {"success": True, "message": f"Graph updated for salt: {request.salt_id}", "data": result}

    except ValueError as e:
        # Could be "Run not found" (404) or "Salt not found" (422)
        msg = str(e)
        status = 404 if "not found" in msg.lower() and "salt" not in msg.lower() else 422
        raise HTTPException(status_code=status, detail=msg)
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        logger.exception("Switch salt unexpected error")
        raise HTTPException(status_code=500, detail=f"Unexpected error: {str(e)}")


@router.post(
    "/saturation/debug-phreeqc",
    summary="Debug: See raw PHREEQC output",
    tags=["Saturation Analysis"],
)
async def debug_phreeqc_output(data: Dict[str, Any] = Body(...)):
    """
    Debug endpoint — runs a single PHREEQC calculation and returns raw output.
    Use this to see exact output format for parser debugging.
    """
    try:
        from app.services.phreeqc_service import PHREEQCService, _concentrate_params, _set_ph_temp
        svc = PHREEQCService()

        base_params = data.get("base_water_parameters") or data.get("params", {
            "pH": 7.2, "Temperature": 25.0,
            "Ca": 80.0, "Mg": 25.0, "Na": 40.0,
            "Cl": 30.0, "SO4": 60.0, "HCO3": 120.0, "SiO2": 15.0,
        })

        # Optional: test at specific CoC + Temperature
        coc   = float(data.get("coc", 1.0))
        temp  = float(data.get("temp_c", 25.0))
        ph    = float(data.get("ph", base_params.get("pH", 7.0) if isinstance(base_params.get("pH"), (int,float)) else 7.0))

        # Concentrate params at given CoC
        concentrated = _concentrate_params(base_params, coc)
        concentrated = _set_ph_temp(concentrated, ph, temp)

        pqi        = svc._build_pqi(concentrated)
        raw_output = await svc._execute_phreeqc_raw(pqi, svc.phreeqc_dat)
        parsed     = svc._parse_phreeqc_output(raw_output)

        return {
            "test_conditions":    {"coc": coc, "temp_c": temp, "ph": ph},
            "concentrated_params": concentrated,
            "pqi_input":          pqi,
            "raw_output_preview": raw_output[:6000],
            "raw_output_tail":    raw_output[-2000:],
            "parsed_si_count":    len(parsed["saturation_indices"]),
            "parsed_si_sample":   parsed["saturation_indices"][:15],
            "ionic_strength":     parsed["ionic_strength"],
            "charge_balance_error_pct": parsed.get("charge_balance_error_pct"),
            "electrical_balance": parsed.get("electrical_balance"),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/saturation/available-salts",
    summary="Get All Available PHREEQC Salts",
    tags=["Saturation Analysis"],
)
async def get_available_salts():
    """
    Returns all mineral/salt names available in the PHREEQC database.
    Result is cached in MongoDB (7-day TTL).

    Response: [{ "name": "Calcite", "chemical_formula": "CaCO3", "phase": "..." }, ...]
    """
    try:
        service = SaturationService()
        salts   = await service.get_available_salts()
        return {
            "success": True,
            "total":   len(salts),
            "salts":   salts,
        }
    except Exception as e:
        logger.exception("Get available salts failed")
        raise HTTPException(status_code=500, detail=str(e))


# ── Saturation run history endpoints ─────────────────────────────────────────

@router.get(
    "/saturation/runs",
    summary="List all saturation runs (paginated)",
    tags=["Saturation Analysis"],
)
async def list_saturation_runs(
    page:      int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    """List all saturation runs, newest first."""
    try:
        skip  = (page - 1) * page_size
        col   = db.db["saturation_runs"]
        total = await col.count_documents({})
        docs  = await col.find({}, {"grid_results": 0}).sort("created_at", -1).skip(skip).limit(page_size).to_list(page_size)
        for d in docs:
            d.pop("_id", None)
        return {"success": True, "total": total, "page": page, "page_size": page_size, "runs": docs}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/saturation/runs/{run_id}",
    summary="Get a specific saturation run by run_id",
    tags=["Saturation Analysis"],
)
async def get_saturation_run(run_id: str):
    """Retrieve full saturation run result by run_id (no recalculation)."""
    try:
        doc = await db.db["saturation_runs"].find_one({"run_id": run_id})
        if not doc:
            raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")
        doc.pop("_id", None)
        return {"success": True, "data": doc}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/saturation/runs/by-customer/{customer_id}",
    summary="Get all saturation runs for a customer",
    tags=["Saturation Analysis"],
)
async def get_runs_by_customer(
    customer_id: str,
    page:        int = Query(1, ge=1),
    page_size:   int = Query(20, ge=1, le=100),
):
    """Retrieve all saturation runs saved under a specific customer_id."""
    try:
        skip  = (page - 1) * page_size
        col   = db.db["saturation_runs"]
        query = {"customer_id": customer_id}
        total = await col.count_documents(query)
        docs  = await col.find(query, {"grid_results": 0}).sort("created_at", -1).skip(skip).limit(page_size).to_list(page_size)
        for d in docs:
            d.pop("_id", None)
        return {"success": True, "customer_id": customer_id, "total": total, "runs": docs}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/saturation/runs/by-asset/{asset_id}",
    summary="Get all saturation runs for an asset",
    tags=["Saturation Analysis"],
)
async def get_runs_by_asset(
    asset_id: str,
    page:     int = Query(1, ge=1),
    page_size:int = Query(20, ge=1, le=100),
):
    """Retrieve all saturation runs saved under a specific asset_id."""
    try:
        skip  = (page - 1) * page_size
        col   = db.db["saturation_runs"]
        query = {"asset_id": asset_id}
        total = await col.count_documents(query)
        docs  = await col.find(query, {"grid_results": 0}).sort("created_at", -1).skip(skip).limit(page_size).to_list(page_size)
        for d in docs:
            d.pop("_id", None)
        return {"success": True, "asset_id": asset_id, "total": total, "runs": docs}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
