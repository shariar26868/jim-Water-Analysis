"""
Water Quality Analysis API - Main Application
FastAPI Backend with 10 Core Features
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import os
from dotenv import load_dotenv
import logging

# Load environment variables
load_dotenv(override=True)

# Import database
from app.db.mongo import db

# Import routes
from app.controllers.water_routes import router as water_router

# Configure logging
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan - startup and shutdown events"""
    # Startup
    logger.info("🚀 Starting Water Quality Analysis API...")
    
    try:
        # Connect to MongoDB
        await db.connect()
        logger.info("✅ Database connected")
        
        # Initialize services
        logger.info("✅ Services initialized")
        
    except Exception as e:
        logger.error(f"❌ Startup failed: {e}")
        raise
    
    yield
    
    # Shutdown
    logger.info("🛑 Shutting down...")
    await db.disconnect()
    logger.info("✅ Shutdown complete")


# Create FastAPI app
app = FastAPI(
    title="Water Quality Analysis API",
    description="AI-powered water quality analysis with PHREEQC calculations",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc"
)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure based on your frontend
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Health check endpoint
@app.get("/")
async def root():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "Water Quality Analysis API",
        "version": "1.0.0"
    }


@app.get("/health")
async def health_check():
    """Detailed health check"""
    try:
        # Check database connection
        await db.client.admin.command('ping')
        db_status = "connected"
    except:
        db_status = "disconnected"
    
    return {
        "status": "ok",
        "database": db_status,
        "openai_configured": bool(os.getenv("OPENAI_API_KEY")),
        "aws_configured": bool(os.getenv("AWS_ACCESS_KEY_ID")),
        "phreeqc_configured": bool(os.getenv("PHREEQC_EXECUTABLE_PATH"))
    }


# Include routers
app.include_router(water_router, prefix="/api/v1", tags=["Water Analysis"])


if __name__ == "__main__":
    import uvicorn
    
    host = os.getenv("APP_HOST", "0.0.0.0")
    port = int(os.getenv("APP_PORT", 8000))
    
    uvicorn.run(
        "main:app",
        host=host,
        port=port,
        reload=True if os.getenv("APP_ENV") == "development" else False
    )