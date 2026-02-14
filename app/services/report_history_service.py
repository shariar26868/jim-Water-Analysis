"""
Report History Service - Save and manage water analysis reports
Generate unique report IDs and maintain history
"""

import logging
from typing import Dict, Any
from datetime import datetime
import uuid

from app.db.mongo import db

logger = logging.getLogger(__name__)


class ReportHistoryService:
    """Manage water analysis report history"""
    
    async def save_report(
        self,
        extracted_parameters: Dict[str, Any],
        chemical_status: Dict[str, Any],
        parameter_graph: Dict[str, Any],
        total_score: Dict[str, Any],
        quality_report: Dict[str, Any],
        chemical_composition: Dict[str, Any],
        biological_indicators: Dict[str, Any],
        compliance_checklist: Dict[str, Any],
        contamination_risk: Dict[str, Any],
        sample_location: str = None,
        sample_date: str = None,
        original_filename: str = None
    ) -> str:
        """
        Save complete water analysis report to database
        
        Returns: report_id
        """
        try:
            # Generate unique report ID
            report_id = self._generate_report_id()
            
            logger.info(f"💾 Saving report: {report_id}")
            
            # Construct complete report document
            report_document = {
                "report_id": report_id,
                "sample_location": sample_location,
                "sample_date": sample_date,
                "original_filename": original_filename,
                
                # Feature 1: Extracted parameters
                "extracted_parameters": extracted_parameters,
                
                # Feature 2: Graph
                "parameter_graph": parameter_graph,
                
                # Feature 3: Chemical status
                "chemical_status": chemical_status,
                
                # Feature 4: Total score
                "total_score": total_score,
                
                # Feature 5: Water quality report
                "quality_report": quality_report,
                
                # Feature 6: Chemical composition
                "chemical_composition": chemical_composition,
                
                # Feature 7: Biological indicators
                "biological_indicators": biological_indicators,
                
                # Feature 8: Compliance checklist
                "compliance_checklist": compliance_checklist,
                
                # Feature 9: Contamination risk
                "contamination_risk": contamination_risk,
                
                # Metadata
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow()
            }
            
            # Save to MongoDB
            await db.save_water_report(report_document)
            
            logger.info(f"✅ Report saved successfully: {report_id}")
            
            return report_id
            
        except Exception as e:
            logger.error(f"❌ Failed to save report: {e}")
            raise Exception(f"Failed to save report: {str(e)}")
    
    async def get_report(self, report_id: str) -> Dict[str, Any]:
        """
        Retrieve a water analysis report by ID
        
        Returns: Complete report document
        """
        try:
            report = await db.get_water_report(report_id)
            
            if not report:
                raise Exception(f"Report {report_id} not found")
            
            return report
            
        except Exception as e:
            logger.error(f"❌ Failed to retrieve report: {e}")
            raise
    
    async def get_report_history(
        self,
        limit: int = 100,
        skip: int = 0
    ) -> Dict[str, Any]:
        """
        Get paginated report history
        
        Returns:
            {
                "reports": [...],
                "total_count": 150
            }
        """
        try:
            reports = await db.get_all_reports(limit=limit, skip=skip)
            
            # Count total
            total_count = await db.db.water_reports.count_documents({})
            
            return {
                "reports": reports,
                "total_count": total_count
            }
            
        except Exception as e:
            logger.error(f"❌ Failed to get report history: {e}")
            raise
    
    async def update_report(
        self,
        report_id: str,
        update_data: Dict[str, Any]
    ) -> bool:
        """
        Update an existing report
        
        Returns: True if updated successfully
        """
        try:
            update_data["updated_at"] = datetime.utcnow()
            
            success = await db.update_water_report(report_id, update_data)
            
            if success:
                logger.info(f"✅ Report {report_id} updated")
            else:
                logger.warning(f"⚠️ Report {report_id} not found for update")
            
            return success
            
        except Exception as e:
            logger.error(f"❌ Failed to update report: {e}")
            raise
    
    async def delete_report(self, report_id: str) -> bool:
        """
        Delete a water analysis report
        
        Returns: True if deleted successfully
        """
        try:
            success = await db.delete_water_report(report_id)
            
            if success:
                logger.info(f"✅ Report {report_id} deleted")
            else:
                logger.warning(f"⚠️ Report {report_id} not found for deletion")
            
            return success
            
        except Exception as e:
            logger.error(f"❌ Failed to delete report: {e}")
            raise
    
    def _generate_report_id(self) -> str:
        """
        Generate unique report ID
        
        Format: WQR-YYYYMMDD-XXXX
        Example: WQR-20240115-A3F2
        """
        date_str = datetime.utcnow().strftime("%Y%m%d")
        unique_suffix = str(uuid.uuid4())[:4].upper()
        
        report_id = f"WQR-{date_str}-{unique_suffix}"
        
        return report_id
    
    async def get_report_summary(self, report_id: str) -> Dict[str, Any]:
        """
        Get summary of a report (for listing)
        
        Returns:
            {
                "report_id": "WQR-...",
                "sample_location": "...",
                "created_at": "...",
                "overall_score": 85.0,
                "wqi_rating": "Good"
            }
        """
        try:
            report = await db.get_water_report(report_id)
            
            if not report:
                raise Exception(f"Report {report_id} not found")
            
            summary = {
                "report_id": report["report_id"],
                "sample_location": report.get("sample_location"),
                "sample_date": report.get("sample_date"),
                "created_at": report["created_at"],
                "overall_score": report["total_score"]["overall_score"],
                "wqi_rating": report["quality_report"]["water_quality_index"]["rating"],
                "original_filename": report.get("original_filename")
            }
            
            return summary
            
        except Exception as e:
            logger.error(f"❌ Failed to get report summary: {e}")
            raise