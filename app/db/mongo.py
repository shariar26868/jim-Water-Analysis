"""
MongoDB Database Connection and Operations
Fully dynamic - no hard-coded collections or schemas
✅ PHREEQC database caching added
"""

from motor.motor_asyncio import AsyncIOMotorClient
from typing import Dict, List, Any, Optional
import os
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class MongoDB:
    client: Optional[AsyncIOMotorClient] = None
    db = None

    @classmethod
    async def connect(cls):
        """Establish MongoDB connection"""
        try:
            mongo_uri = os.getenv("MONGO_URI")
            db_name = os.getenv("MONGO_DB_NAME", "water_quality_db")
            
            cls.client = AsyncIOMotorClient(mongo_uri)
            cls.db = cls.client[db_name]
            
            # Test connection
            await cls.client.admin.command('ping')
            logger.info(f"✅ Connected to MongoDB: {db_name}")
            
            # Create indexes
            await cls._create_indexes()
            
        except Exception as e:
            logger.error(f"❌ MongoDB connection failed: {e}")
            raise

    @classmethod
    async def _create_indexes(cls):
        """Create database indexes for performance"""
        try:
            # Water reports index
            await cls.db.water_reports.create_index("report_id", unique=True)
            await cls.db.water_reports.create_index("created_at")
            
            # Parameter standards index
            await cls.db.parameter_standards.create_index("parameter_name", unique=True)
            
            # Formulas index
            await cls.db.calculation_formulas.create_index("formula_name", unique=True)
            
            # ✅ NEW: PHREEQC cache index
            await cls.db.phreeqc_database_cache.create_index("database_name", unique=True)
            await cls.db.phreeqc_database_cache.create_index("cached_at")
            
            logger.info("✅ Database indexes created")
        except Exception as e:
            logger.warning(f"Index creation warning: {e}")

    @classmethod
    async def disconnect(cls):
        """Close MongoDB connection"""
        if cls.client:
            cls.client.close()
            logger.info("✅ MongoDB connection closed")

    @classmethod
    async def get_collection(cls, collection_name: str):
        """Get a collection dynamically"""
        return cls.db[collection_name]

    # ========== WATER REPORTS ==========
    
    @classmethod
    async def save_water_report(cls, report_data: Dict[str, Any]) -> str:
        """Save complete water analysis report"""
        collection = cls.db.water_reports
        
        report_data["created_at"] = datetime.utcnow()
        report_data["updated_at"] = datetime.utcnow()
        
        result = await collection.insert_one(report_data)
        logger.info(f"✅ Report saved: {report_data.get('report_id')}")
        
        return str(result.inserted_id)

    @classmethod
    async def get_water_report(cls, report_id: str) -> Optional[Dict]:
        """Retrieve water report by ID"""
        collection = cls.db.water_reports
        report = await collection.find_one({"report_id": report_id})
        return report

    @classmethod
    async def get_all_reports(cls, limit: int = 100, skip: int = 0) -> List[Dict]:
        """Get all water reports with pagination"""
        collection = cls.db.water_reports
        cursor = collection.find().sort("created_at", -1).skip(skip).limit(limit)
        reports = await cursor.to_list(length=limit)
        return reports

    @classmethod
    async def update_water_report(cls, report_id: str, update_data: Dict) -> bool:
        """Update existing water report"""
        collection = cls.db.water_reports
        
        update_data["updated_at"] = datetime.utcnow()
        
        result = await collection.update_one(
            {"report_id": report_id},
            {"$set": update_data}
        )
        
        return result.modified_count > 0

    @classmethod
    async def delete_water_report(cls, report_id: str) -> bool:
        """Delete water report"""
        collection = cls.db.water_reports
        result = await collection.delete_one({"report_id": report_id})
        return result.deleted_count > 0

    # ========== PARAMETER STANDARDS (Dynamic Thresholds) ==========
    
    @classmethod
    async def get_parameter_standard(cls, parameter_name: str) -> Optional[Dict]:
        """Get threshold standards for a parameter"""
        collection = cls.db.parameter_standards
        return await collection.find_one({"parameter_name": parameter_name})

    @classmethod
    async def get_all_parameter_standards(cls) -> List[Dict]:
        """Get all parameter standards"""
        collection = cls.db.parameter_standards
        cursor = collection.find()
        return await cursor.to_list(length=None)

    @classmethod
    async def save_parameter_standard(cls, standard_data: Dict) -> str:
        """Save or update parameter standard"""
        collection = cls.db.parameter_standards
        
        result = await collection.update_one(
            {"parameter_name": standard_data["parameter_name"]},
            {"$set": standard_data},
            upsert=True
        )
        
        return standard_data["parameter_name"]

    # ========== CALCULATION FORMULAS (Dynamic) ==========
    
    @classmethod
    async def get_formula(cls, formula_name: str) -> Optional[Dict]:
        """Get calculation formula by name"""
        collection = cls.db.calculation_formulas
        return await collection.find_one({"formula_name": formula_name})

    @classmethod
    async def get_all_formulas(cls) -> List[Dict]:
        """Get all calculation formulas"""
        collection = cls.db.calculation_formulas
        cursor = collection.find()
        return await cursor.to_list(length=None)

    @classmethod
    async def save_formula(cls, formula_data: Dict) -> str:
        """Save or update calculation formula"""
        collection = cls.db.calculation_formulas
        
        result = await collection.update_one(
            {"formula_name": formula_data["formula_name"]},
            {"$set": formula_data},
            upsert=True
        )
        
        return formula_data["formula_name"]

    # ========== GRAPH TEMPLATES ==========
    
    @classmethod
    async def get_graph_template(cls, graph_type: str) -> Optional[Dict]:
        """Get graph template configuration"""
        collection = cls.db.graph_templates
        return await collection.find_one({"graph_type": graph_type})

    # ========== SCORING CONFIGURATION ==========
    
    @classmethod
    async def get_scoring_config(cls, scoring_type: str) -> Optional[Dict]:
        """Get scoring configuration"""
        collection = cls.db.scoring_config
        return await collection.find_one({"scoring_type": scoring_type})

    # ========== COMPLIANCE RULES ==========
    
    @classmethod
    async def get_compliance_rules(cls, standard: str = None) -> List[Dict]:
        """Get compliance rules (optionally filtered by standard)"""
        collection = cls.db.compliance_rules
        
        query = {"standard": standard} if standard else {}
        cursor = collection.find(query)
        
        return await cursor.to_list(length=None)

    # ========== SUGGESTION TEMPLATES ==========
    
    @classmethod
    async def get_suggestion_templates(cls, category: str = None) -> List[Dict]:
        """Get suggestion templates"""
        collection = cls.db.suggestion_templates
        
        query = {"category": category} if category else {}
        cursor = collection.find(query)
        
        return await cursor.to_list(length=None)

    # ========== PHREEQC CONFIGURATION ==========
    
    @classmethod
    async def get_phreeqc_config(cls) -> Optional[Dict]:
        """Get PHREEQC configuration"""
        collection = cls.db.phreeqc_config
        return await collection.find_one()

    # ========== PHREEQC DATABASE CACHING (NEW) ==========
    
    @classmethod
    async def cache_phreeqc_database_info(cls, database_name: str, info: Dict) -> str:
        """
        Cache PHREEQC database information (minerals, species, elements, etc.)
        for performance optimization
        
        Args:
            database_name: Database name (e.g., "default", "pitzer")
            info: Dictionary containing database info
                {
                    "minerals": [...],
                    "species": [...],
                    "elements": [...],
                    "gases": [...],
                    "exchange_species": [...],
                    "surface_species": [...]
                }
        
        Returns:
            database_name
        """
        collection = cls.db.phreeqc_database_cache
        
        cache_doc = {
            "database_name": database_name,
            "info": info,
            "cached_at": datetime.utcnow(),
            "version": "1.0"
        }
        
        result = await collection.update_one(
            {"database_name": database_name},
            {"$set": cache_doc},
            upsert=True
        )
        
        logger.info(f"✅ Cached PHREEQC database info: {database_name}")
        logger.debug(f"   - Minerals: {len(info.get('minerals', []))}")
        logger.debug(f"   - Species: {len(info.get('species', []))}")
        logger.debug(f"   - Elements: {len(info.get('elements', []))}")
        
        return database_name
    
    @classmethod
    async def get_cached_phreeqc_info(cls, database_name: str) -> Optional[Dict]:
        """
        Get cached PHREEQC database information
        
        Returns None if:
        - No cache exists
        - Cache is older than 7 days
        
        Args:
            database_name: Database name (e.g., "default", "pitzer")
        
        Returns:
            Dictionary with database info or None
        """
        collection = cls.db.phreeqc_database_cache
        cache = await collection.find_one({"database_name": database_name})
        
        if not cache:
            logger.debug(f"No cache found for database: {database_name}")
            return None
        
        # Check cache age
        cached_at = cache.get("cached_at")
        if cached_at:
            age = datetime.utcnow() - cached_at
            
            if age.days < 7:
                logger.info(f"📦 Using cached PHREEQC info: {database_name} (age: {age.days} days)")
                return cache.get("info")
            else:
                logger.info(f"⏰ Cache expired for {database_name} (age: {age.days} days)")
                return None
        
        return None
    
    @classmethod
    async def clear_phreeqc_cache(cls, database_name: str = None) -> int:
        """
        Clear PHREEQC database cache
        
        Args:
            database_name: Specific database to clear, or None to clear all
        
        Returns:
            Number of cache entries deleted
        """
        collection = cls.db.phreeqc_database_cache
        
        if database_name:
            result = await collection.delete_one({"database_name": database_name})
            deleted = result.deleted_count
            logger.info(f"✅ Cleared cache for: {database_name}")
        else:
            result = await collection.delete_many({})
            deleted = result.deleted_count
            logger.info(f"✅ Cleared all PHREEQC cache ({deleted} entries)")
        
        return deleted
    
    @classmethod
    async def get_all_cached_databases(cls) -> List[Dict]:
        """
        Get list of all cached PHREEQC databases
        
        Returns:
            List of cache info (database_name, cached_at, sizes)
        """
        collection = cls.db.phreeqc_database_cache
        cursor = collection.find({}, {
            "database_name": 1,
            "cached_at": 1,
            "version": 1,
            "info.minerals": 1,
            "info.species": 1
        })
        
        caches = await cursor.to_list(length=None)
        
        # Format response
        result = []
        for cache in caches:
            info = cache.get("info", {})
            result.append({
                "database_name": cache.get("database_name"),
                "cached_at": cache.get("cached_at"),
                "version": cache.get("version"),
                "minerals_count": len(info.get("minerals", [])),
                "species_count": len(info.get("species", []))
            })
        
        return result

    # ========== GENERIC OPERATIONS ==========
    
    @classmethod
    async def insert_one(cls, collection_name: str, document: Dict) -> str:
        """Generic insert operation"""
        collection = cls.db[collection_name]
        result = await collection.insert_one(document)
        return str(result.inserted_id)

    @classmethod
    async def find_one(cls, collection_name: str, query: Dict) -> Optional[Dict]:
        """Generic find one operation"""
        collection = cls.db[collection_name]
        return await collection.find_one(query)

    @classmethod
    async def find_many(cls, collection_name: str, query: Dict = None) -> List[Dict]:
        """Generic find many operation"""
        collection = cls.db[collection_name]
        cursor = collection.find(query or {})
        return await cursor.to_list(length=None)

    @classmethod
    async def update_one(cls, collection_name: str, query: Dict, update: Dict) -> bool:
        """Generic update operation"""
        collection = cls.db[collection_name]
        result = await collection.update_one(query, {"$set": update})
        return result.modified_count > 0

    @classmethod
    async def delete_one(cls, collection_name: str, query: Dict) -> bool:
        """Generic delete operation"""
        collection = cls.db[collection_name]
        result = await collection.delete_one(query)
        return result.deleted_count > 0


# Database instance
db = MongoDB()