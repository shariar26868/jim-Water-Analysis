# 🌊 Water Quality Analysis Backend

AI-powered water quality analysis system with PHREEQC integration, dynamic OCR, and comprehensive reporting.

---

## ✨ Features

### 🎯 10 Core Features

1. **PDF OCR Extraction** - AI-powered extraction of all chemical parameters (GPT-4o Vision)
2. **Parameter Comparison Graph** - Dynamic bar chart with prompt-based color modification
3. **Chemical Status Report** - PHREEQC calculations (saturation indices, ionic strength)
4. **Total Analysis Score** - Weighted scoring system (0-100)
5. **Water Quality Report** - WQI, compliance score, risk factor
6. **Chemical Composition** - Parameter-by-parameter analysis with status
7. **Biological Indicators** - Bacteria, pathogen, organic material analysis
8. **Compliance Checklist** - WHO/EPA/Bangladesh standards checking
9. **Contamination Risk** - Heavy metals, organic compounds, microbiological risks
10. **Report History** - Unique report IDs with full history management

### 🔥 Key Highlights

- ✅ **100% Dynamic** - No hard-coded parameters or thresholds
- ✅ **Database-Driven** - All standards, formulas, and thresholds in MongoDB
- ✅ **AI-Powered** - OpenAI GPT-4o for OCR and natural language processing
- ✅ **PHREEQC Integration** - Scientific water chemistry calculations
- ✅ **Cloud Storage** - AWS S3 for PDFs and graphs
- ✅ **RESTful API** - FastAPI with automatic documentation

---

## 🚀 Quick Start

### Prerequisites

- Python 3.10+
- MongoDB Atlas account
- AWS S3 bucket
- OpenAI API key
- PHREEQC installed on system

### Installation

1. **Clone repository**
   ```bash
   git clone <repository-url>
   cd water-quality-backend
   ```

2. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

3. **Install PHREEQC**
   ```bash
   # Ubuntu/Debian
   sudo apt-get install phreeqc
   
   # macOS
   brew install phreeqc
   
   # Windows: Download from https://www.usgs.gov/software/phreeqc
   ```

4. **Configure environment**
   ```bash
   cp .env.example .env
   # Edit .env with your credentials
   ```

5. **Seed database** (Optional - loads initial standards)
   ```bash
   python scripts/seed_database.py
   ```

6. **Run application**
   ```bash
   python main.py
   ```

7. **Access API documentation**
   ```
   http://localhost:8000/api/docs
   ```

---

## 📋 API Endpoints

### Water Analysis

#### Analyze Water Sample
```http
POST /api/v1/water/analyze
Content-Type: multipart/form-data

Parameters:
- file: PDF file (required)
- sample_location: string (optional)
- sample_date: string (optional)

Response: Complete analysis with all 10 features
```

#### Modify Graph with Prompt
```http
POST /api/v1/water/graph/modify
Content-Type: application/json

{
  "report_id": "WQR-20240115-A3F2",
  "prompt": "Make pH bar green and TDS bar red"
}

Response: Updated graph URL
```

#### Get Report History
```http
GET /api/v1/water/reports?page=1&page_size=20

Response: Paginated report list
```

#### Get Specific Report
```http
GET /api/v1/water/reports/{report_id}

Response: Complete report data
```

#### Delete Report
```http
DELETE /api/v1/water/reports/{report_id}

Response: Deletion confirmation
```

---

## 🗄️ Database Collections

### Core Collections

1. **water_reports** - All analysis reports
2. **parameter_standards** - Dynamic thresholds for each parameter
3. **calculation_formulas** - PHREEQC and custom formulas
4. **graph_templates** - Graph styling configuration
5. **scoring_config** - Scoring weights and rating scales
6. **compliance_rules** - Regulatory standards (WHO, EPA, etc.)
7. **phreeqc_config** - PHREEQC settings
8. **suggestion_templates** - AI suggestion templates

---

## 🧪 Testing

```bash
# Run all tests
pytest

# Run specific test
pytest tests/test_ocr_service.py

# Run with coverage
pytest --cov=app tests/
```

---

## 📊 Example Usage

### Python Client

```python
import requests

# Upload and analyze
with open('water_sample.pdf', 'rb') as f:
    files = {'file': f}
    response = requests.post(
        'http://localhost:8000/api/v1/water/analyze',
        files=files
    )
    
result = response.json()
print(f"Report ID: {result['report_id']}")
print(f"Total Score: {result['total_score']['overall_score']}/100")
print(f"WQI Rating: {result['quality_report']['water_quality_index']['rating']}")
```

### cURL

```bash
curl -X POST http://localhost:8000/api/v1/water/analyze \
  -F "file=@water_sample.pdf" \
  -F "sample_location=Dhaka, Bangladesh"
```

---

## 🔧 Configuration

### Environment Variables

See `.env.example` for all required variables:

- `OPENAI_API_KEY` - OpenAI API key
- `AWS_ACCESS_KEY_ID` - AWS credentials
- `AWS_SECRET_ACCESS_KEY` - AWS credentials
- `AWS_S3_BUCKET` - S3 bucket name
- `MONGO_URI` - MongoDB connection string
- `PHREEQC_EXECUTABLE_PATH` - Path to PHREEQC

### Adding New Parameters

1. Add parameter standard to MongoDB:
```javascript
db.parameter_standards.insertOne({
  "parameter_name": "New_Parameter",
  "unit": "mg/L",
  "thresholds": {
    "optimal": {"min": 0, "max": 10},
    "good": {"min": 10, "max": 20},
    "warning": {"min": 20, "max": 50},
    "critical": {"min": 50, "max": null}
  },
  "standards": {
    "WHO": {"max": 20}
  }
})
```

2. No code changes needed! System automatically detects and processes.

---

## 📈 Architecture

```
┌─────────────┐
│  PDF Upload │
└──────┬──────┘
       ↓
┌─────────────────┐
│  OCR Service    │ → OpenAI GPT-4o Vision
└──────┬──────────┘
       ↓
┌─────────────────┐
│ PHREEQC Service │ → Ion balancing, SI
└──────┬──────────┘
       ↓
┌─────────────────┐
│ Graph Service   │ → Matplotlib + S3
└──────┬──────────┘
       ↓
┌─────────────────┐
│ Analysis Suite  │ → Scoring, Compliance, Risk
└──────┬──────────┘
       ↓
┌─────────────────┐
│ MongoDB Storage │ → Report history
└─────────────────┘
```

---

## 🛠️ Troubleshooting

### PHREEQC Not Found
```bash
# Check if PHREEQC is installed
which phreeqc

# Set correct path in .env
PHREEQC_EXECUTABLE_PATH=/usr/local/bin/phreeqc
```

### MongoDB Connection Failed
```bash
# Check connection string format
MONGO_URI=mongodb+srv://username:password@cluster.mongodb.net/

# Test connection
python -c "from app.db.mongo import db; import asyncio; asyncio.run(db.connect())"
```

### OpenAI API Errors
```bash
# Verify API key
echo $OPENAI_API_KEY

# Check quota: https://platform.openai.com/usage
```

---

## 📝 License

MIT License - See LICENSE file

---

## 🙏 Acknowledgments

- PHREEQC by USGS
- OpenAI GPT-4o
- FastAPI framework
- MongoDB Atlas

---

## 📞 Support

For issues or questions:
- Open an issue on GitHub
- Email: semonshaikat702@gmail.com
- Documentation: `/api/docs`

---

**Built with ❤️ for environmental monitoring and public health**
