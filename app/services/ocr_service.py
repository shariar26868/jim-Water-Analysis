
"""
OCR Service - FIXED VERSION
✅ Proper image fetching from PDF
✅ Better error handling
✅ Image validation
✅ Memory optimization
✅ FIXED: Validation response detection
✅ FIXED: Better Poppler installation guidance
✅ Enhanced debugging
"""

import os
import json
import base64
import logging
import platform
import shutil
from typing import Dict, Any, List, Optional
from datetime import datetime
from io import BytesIO

from openai import AsyncOpenAI
from pdf2image import convert_from_bytes
from PyPDF2 import PdfReader
from PIL import Image
import re

logger = logging.getLogger(__name__)


# ===============================
# UTILS: SANITIZE NUMBERS
# ===============================
def _sanitize_number(value: Any) -> Optional[float]:
    """Convert a value to float if possible, else return None"""
    if value is None:
        return None

    # If already numeric, keep
    if isinstance(value, (int, float)):
        return float(value)

    # Convert strings like "<0.01", ">0.5", "0.05"
    if isinstance(value, str):
        try:
            # Remove <, >, whitespace
            cleaned = value.replace("<", "").replace(">", "").strip()
            return float(cleaned)
        except ValueError:
            # Non-numeric like 'NYS', 'BDL' → None
            return None

    return None


def _sanitize_parameters(parameters: Dict[str, Any]) -> Dict[str, Any]:
    """Sanitize all 'value' and 'detection_limit' fields in parameters dict"""
    for param_name, param_data in parameters.items():
        if isinstance(param_data, dict):
            for key in ["value", "detection_limit"]:
                if key in param_data:
                    param_data[key] = _sanitize_number(param_data[key])
    return parameters


class OCRService:
    """Extract chemical parameters from PDF and Images using AI - FIXED"""
    
    def __init__(self):
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY environment variable not set")
        
        self.client = AsyncOpenAI(api_key=api_key)
        self.model = "gpt-4o"
        
        # Check poppler availability
        self.poppler_available = self._check_poppler()
        if self.poppler_available:
            logger.info("✅ Poppler available - PDF Image OCR enabled")
        else:
            logger.warning("⚠️ Poppler not available - PDF Text-only OCR mode")
    
    # =====================================================
    # PUBLIC API - UNIFIED ENTRY POINT
    # =====================================================
    async def extract_from_file(self, file_content: bytes, filename: str, content_type: str) -> Dict[str, Any]:
        """
        Universal file extraction - handles PDF and Images
        
        Args:
            file_content: File bytes
            filename: Original filename
            content_type: MIME type (application/pdf, image/jpeg, etc.)
            
        Returns:
            Extracted parameters with metadata
        """
        try:
            logger.info(f"🔍 Starting extraction for {filename} ({content_type})")
            
            # Validate file content
            if not file_content:
                raise ValueError("Empty file content")
            
            # Route based on file type
            if content_type == "application/pdf":
                return await self.extract_from_pdf(file_content, filename)
            elif content_type in ["image/jpeg", "image/jpg", "image/png", "image/tiff", "image/tif"]:
                return await self.extract_from_image(file_content, filename)
            else:
                raise ValueError(f"Unsupported file type: {content_type}")
                
        except Exception as e:
            logger.exception("❌ File extraction failed")
            raise Exception(f"File extraction failed: {str(e)}")
    
    # =====================================================
    # PDF EXTRACTION - FIXED
    # =====================================================
    async def extract_from_pdf(self, pdf_content: bytes, filename: str) -> Dict[str, Any]:
        """Extract all water quality parameters from PDF - FIXED VERSION"""
        try:
            logger.info(f"🔍 PDF OCR started: {filename}")
            
            # Try image-based OCR first (if poppler available)
            if self.poppler_available:
                try:
                    images = self._pdf_to_images_safe(pdf_content)
                    
                    if images and len(images) > 0:
                        logger.info(f"📄 PDF Image OCR mode ({len(images)} pages)")
                        
                        # Extract from images
                        parameters = await self._extract_from_images(images)
                        
                        # Clean up images from memory
                        del images
                        
                        if parameters:
                            # Validate extraction
                            validation = await self.validate_extraction(parameters)
                            
                            return {
                                "parameters": parameters,
                                "metadata": {
                                    "source_file": filename,
                                    "method": "pdf-image-ocr",
                                    "pages_processed": len(images) if images else 0,
                                    "extraction_date": datetime.utcnow().isoformat()
                                },
                                "validation": validation,
                                "created_at": datetime.utcnow()
                            }
                    
                    logger.warning("⚠️ PDF to image conversion returned no images, falling back to text")
                    
                except Exception as img_error:
                    logger.warning(f"⚠️ Image-based OCR failed: {img_error}, falling back to text")
            
            # Fallback: Text-only extraction
            logger.info("📄 PDF Text-only OCR fallback")
            text = self._extract_text_from_pdf(pdf_content)
            
            if not text or len(text.strip()) < 10:
                raise ValueError("No extractable text found in PDF")
            
            parameters = await self._extract_from_text(text)
            
            if not parameters:
                raise ValueError("No parameters extracted from PDF text")
            
            # Validate
            validation = await self.validate_extraction(parameters)
            
            return {
                "parameters": parameters,
                "metadata": {
                    "source_file": filename,
                    "method": "pdf-text-only",
                    "pages_processed": 1,
                    "extraction_date": datetime.utcnow().isoformat()
                },
                "validation": validation,
                "created_at": datetime.utcnow()
            }
            
        except Exception as e:
            logger.exception("❌ PDF extraction failed")
            raise Exception(f"PDF extraction failed: {str(e)}")
    
    # =====================================================
    # IMAGE EXTRACTION - FIXED
    # =====================================================
    async def extract_from_image(self, image_content: bytes, filename: str) -> Dict[str, Any]:
        """
        Extract parameters from image file (JPG, PNG, TIFF) - FIXED
        """
        try:
            logger.info(f"🖼️ Image OCR started: {filename}")
            
            # Validate image content
            if not image_content:
                raise ValueError("Empty image content")
            
            # Load image from bytes
            try:
                image = Image.open(BytesIO(image_content))
            except Exception as e:
                raise ValueError(f"Invalid image file: {str(e)}")
            
            # Log image info
            logger.info(f"📐 Image size: {image.size}, mode: {image.mode}, format: {image.format}")
            
            # Validate image
            if image.size[0] < 100 or image.size[1] < 100:
                raise ValueError(f"Image too small: {image.size}")
            
            # Convert to RGB if needed (for consistency)
            if image.mode not in ['RGB', 'L']:
                logger.info(f"🔄 Converting image from {image.mode} to RGB")
                image = image.convert('RGB')
            
            # Extract using GPT-4o Vision
            img_base64 = self._image_to_base64(image)
            
            # Clean up
            del image
            
            parameters = await self._extract_with_vision(img_base64, page_num=1)
            
            if not parameters:
                raise ValueError("No parameters extracted from image")
            
            # Sanitize parameters
            parameters = _sanitize_parameters(parameters)
            
            # Validate extraction
            validation = await self.validate_extraction(parameters)
            
            logger.info(f"✅ Image OCR complete: {len(parameters)} parameters extracted")
            
            return {
                "parameters": parameters,
                "metadata": {
                    "source_file": filename,
                    "method": "image-ocr",
                    "image_format": "RGB",
                    "pages_processed": 1,
                    "extraction_date": datetime.utcnow().isoformat()
                },
                "validation": validation,
                "created_at": datetime.utcnow()
            }
            
        except Exception as e:
            logger.error(f"❌ Image extraction failed: {e}")
            raise Exception(f"Image extraction failed: {str(e)}")
    
    # =====================================================
    # POPPLER DETECTION - FIXED WITH BETTER GUIDANCE
    # =====================================================
    def _check_poppler(self) -> bool:
        """Check if poppler is available on system - FIXED"""
        system = platform.system()
        
        if system == "Windows":
            # ✅ IMPROVED: Check environment variable first
            poppler_env = os.getenv("POPPLER_PATH")
            if poppler_env and os.path.exists(poppler_env):
                logger.info(f"✅ Found Poppler from POPPLER_PATH: {poppler_env}")
                return True
            
            common_paths = [
                r"C:\poppler\Library\bin",
                r"C:\Program Files\poppler\bin",
                r"C:\poppler-bin\bin",
                os.path.expanduser(r"~\poppler\bin"),
                r"C:\poppler\bin"  # ✅ ADDED: Common install location
            ]
            
            for path in common_paths:
                if os.path.exists(path):
                    logger.info(f"✅ Found Poppler at: {path}")
                    return True
            
            # ✅ IMPROVED: More helpful error message
            logger.warning("⚠️ Poppler not found in common Windows paths")
            logger.warning("📥 To install Poppler on Windows:")
            logger.warning("   1. Download: https://github.com/oschwartz10612/poppler-windows/releases")
            logger.warning("   2. Extract to C:\\poppler\\")
            logger.warning("   3. Or set POPPLER_PATH environment variable to the bin directory")
            logger.warning("   4. Alternative: conda install -c conda-forge poppler")
            return False
        
        else:
            # Linux/Mac: Check if pdftoppm in PATH
            has_poppler = shutil.which("pdftoppm") is not None
            if not has_poppler:
                logger.warning("⚠️ Poppler not found on Linux/Mac")
                logger.warning("📥 To install: sudo apt-get install poppler-utils (Ubuntu/Debian)")
                logger.warning("📥 Or: brew install poppler (macOS)")
            return has_poppler
    
    def _get_poppler_path(self) -> Optional[str]:
        """Get poppler path for current OS - FIXED"""
        system = platform.system()
        
        if system == "Windows":
            # ✅ IMPROVED: Check environment variable first
            poppler_env = os.getenv("POPPLER_PATH")
            if poppler_env and os.path.exists(poppler_env):
                return poppler_env
            
            common_paths = [
                r"C:\poppler\Library\bin",
                r"C:\Program Files\poppler\bin",
                r"C:\poppler-bin\bin",
                r"C:\poppler\bin"
            ]
            
            for path in common_paths:
                if os.path.exists(path):
                    return path
            return None
        
        # Linux/Mac don't need explicit path
        return None
    
    # =====================================================
    # PDF → IMAGES (SAFE) - FIXED
    # =====================================================
    def _pdf_to_images_safe(self, pdf_content: bytes) -> Optional[List[Image.Image]]:
        """
        Safely convert PDF to images - FIXED VERSION
        
        Returns:
            List of PIL Images or None if conversion fails
        """
        try:
            if not pdf_content:
                logger.error("Empty PDF content")
                return None
            
            poppler_path = self._get_poppler_path()
            
            logger.info(f"Converting PDF to images (DPI=300, max 3 pages)...")
            
            images = convert_from_bytes(
                pdf_content,
                dpi=300,
                first_page=1,
                last_page=3,
                poppler_path=poppler_path,
                fmt='jpeg',
                thread_count=2
            )
            
            if not images or len(images) == 0:
                logger.warning("PDF conversion returned empty list")
                return None
            
            logger.info(f"✅ Successfully converted {len(images)} pages to images")
            
            # Validate images
            valid_images = []
            for idx, img in enumerate(images, 1):
                if img and hasattr(img, 'size') and img.size[0] > 0 and img.size[1] > 0:
                    valid_images.append(img)
                    logger.debug(f"Page {idx}: {img.size}, {img.mode}")
                else:
                    logger.warning(f"Page {idx}: Invalid image")
            
            if not valid_images:
                logger.error("No valid images after conversion")
                return None
            
            return valid_images
            
        except Exception as e:
            logger.error(f"⚠️ PDF→Image conversion failed: {e}")
            return None
    
    # =====================================================
    # IMAGE OCR (Multi-page support) - FIXED
    # =====================================================
    async def _extract_from_images(self, images: List[Image.Image]) -> Dict[str, Any]:
        """Extract from multiple images - FIXED"""
        all_parameters: Dict[str, Any] = {}
        
        if not images:
            logger.error("No images provided for extraction")
            return {}
        
        for idx, image in enumerate(images, start=1):
            try:
                logger.info(f"📊 Processing page {idx}/{len(images)}")
                
                # Validate image
                if not image or not hasattr(image, 'size'):
                    logger.warning(f"Page {idx}: Invalid image object")
                    continue
                
                img_base64 = self._image_to_base64(image)
                page_params = await self._extract_with_vision(img_base64, idx)
                
                if page_params:
                    all_parameters.update(page_params)
                    logger.info(f"✅ Page {idx}: Extracted {len(page_params)} parameters")
                else:
                    logger.warning(f"⚠️ Page {idx}: No parameters extracted")
                    
            except Exception as e:
                logger.error(f"❌ Failed to process page {idx}: {e}")
                continue
        
        # Sanitize numbers
        all_parameters = _sanitize_parameters(all_parameters)
        
        logger.info(f"✅ Total extracted: {len(all_parameters)} unique parameters")
        return all_parameters
    
    async def _extract_with_vision(self, image_base64: str, page_num: int) -> Dict[str, Any]:
        """Use GPT-4o Vision to extract parameters from image - FIXED"""
        try:
            if not image_base64:
                logger.error(f"Page {page_num}: Empty base64 image")
                return {}
            
            prompt = self._build_extraction_prompt_detailed()
            
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are an expert water quality analyst. Extract ALL chemical, physical, and biological parameters from water analysis reports with precision."
                    },
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{image_base64}",
                                    "detail": "high"
                                }
                            }
                        ]
                    }
                ],
                max_tokens=2000,
                temperature=0.1
            )
            
            content = response.choices[0].message.content
            
            if not content:
                logger.warning(f"Page {page_num}: Empty GPT response")
                return {}
            
            logger.debug(f"GPT-4o Response (first 200 chars): {content[:200]}...")
            
            parameters = self._parse_gpt_response(content)
            
            # Sanitize
            parameters = _sanitize_parameters(parameters)
            
            if parameters:
                logger.info(f"✅ Page {page_num}: Extracted {len(parameters)} parameters")
            else:
                logger.warning(f"⚠️ Page {page_num}: No parameters parsed")
            
            return parameters
            
        except Exception as e:
            logger.error(f"❌ Vision API failed for page {page_num}: {e}")
            return {}
    
    # =====================================================
    # TEXT FALLBACK (PDF) - FIXED
    # =====================================================
    def _extract_text_from_pdf(self, pdf_content: bytes) -> str:
        """Extract raw text from PDF - FIXED"""
        try:
            if not pdf_content:
                return ""
            
            reader = PdfReader(BytesIO(pdf_content))
            text = ""
            
            for page_num, page in enumerate(reader.pages, 1):
                try:
                    page_text = page.extract_text()
                    if page_text:
                        text += page_text + "\n"
                        logger.debug(f"Page {page_num}: Extracted {len(page_text)} chars")
                except Exception as e:
                    logger.warning(f"Failed to extract text from page {page_num}: {e}")
                    continue
            
            text = text.strip()
            logger.info(f"Extracted {len(text)} total characters from PDF")
            
            return text
            
        except Exception as e:
            logger.error(f"❌ Text extraction failed: {e}")
            return ""
    
    async def _extract_from_text(self, text: str) -> Dict[str, Any]:
        """Extract parameters from plain text - FIXED"""
        try:
            if not text or len(text.strip()) < 10:
                logger.error("Insufficient text for extraction")
                return {}
            
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "Extract water quality parameters from text accurately."},
                    {"role": "user", "content": f"{self._build_extraction_prompt_detailed()}\n\nText content:\n{text[:4000]}"}  # Limit text
                ],
                temperature=0.1,
                max_tokens=2000
            )
            
            content = response.choices[0].message.content
            
            if not content:
                logger.warning("Empty response from text extraction")
                return {}
            
            parameters = self._parse_gpt_response(content)
            
            # Sanitize
            parameters = _sanitize_parameters(parameters)
            
            logger.info(f"✅ Text extraction: {len(parameters)} parameters")
            
            return parameters
            
        except Exception as e:
            logger.error(f"❌ Text extraction failed: {e}")
            return {}
    
    # =====================================================
    # PROMPT (DETAILED)
    # =====================================================
    def _build_extraction_prompt_detailed(self) -> str:
        """Original detailed extraction prompt"""
        return """
Extract ALL water quality parameters from this image/document. 

IMPORTANT INSTRUCTIONS:
1. Extract EVERY parameter you see (chemical, physical, biological)
2. Include parameter name, numeric value, and unit
3. For pH, temperature without units, set unit as null
4. Common parameters include: pH, Temperature, TDS, Conductivity, Alkalinity, Hardness, 
   Calcium, Magnesium, Sodium, Potassium, Chloride, Sulfate, Nitrate, Fluoride, Iron, 
   Manganese, Arsenic, Lead, Mercury, Bacteria count, BOD, COD, Turbidity, Color, Odor, etc.
5. DO NOT skip any parameter, even if unfamiliar
6. If a parameter has "<" or ">" (like "<0.01"), extract the numeric value and note detection_limit
7. If value is "BDL" or "Below Detection Limit", use 0 for value and note in detection_limit

Return ONLY valid JSON in this EXACT format:
{
  "pH": {
    "value": 7.8,
    "unit": null,
    "detection_limit": null
  },
  "Calcium": {
    "value": 85.5,
    "unit": "mg/L",
    "detection_limit": null
  },
  "Temperature": {
    "value": 25.0,
    "unit": "°C",
    "detection_limit": null
  },
  "TDS": {
    "value": 450,
    "unit": "mg/L",
    "detection_limit": null
  },
  "Arsenic": {
    "value": 0.01,
    "unit": "mg/L",
    "detection_limit": "<0.01"
  },
  "Bacteria_Count": {
    "value": 0,
    "unit": "CFU/100mL",
    "detection_limit": "BDL"
  }
}

CRITICAL: Return ONLY the JSON object, no explanation, no markdown code blocks, no extra text.
"""
    
    # =====================================================
    # JSON PARSING (ROBUST + FALLBACK) - FIXED
    # =====================================================
    def _parse_gpt_response(self, content: str) -> Dict[str, Any]:
        """Parse GPT response to extract JSON - FIXED"""
        try:
            if not content:
                logger.error("Empty content to parse")
                return {}
            
            # Remove markdown code blocks
            content = content.strip()
            if content.startswith("```json"):
                content = content[7:]
            elif content.startswith("```"):
                content = content[3:]
            if content.endswith("```"):
                content = content[:-3]
            content = content.strip()
            
            # Parse JSON
            parameters = json.loads(content)
            
            if not isinstance(parameters, dict):
                logger.error(f"Parsed result is not a dict: {type(parameters)}")
                return {}
            
            # ✅ FIXED: Check if this is a validation result instead of parameters
            if isinstance(parameters, dict):
                # Validation responses have these specific keys
                validation_keys = {'valid', 'errors', 'warnings', 'suggestions'}
                if validation_keys.issubset(set(parameters.keys())):
                    logger.info("🔍 Detected validation response, not parameters - skipping")
                    return {}
                
                # Another check: if ALL keys are validation-like
                if all(k in validation_keys for k in parameters.keys()):
                    logger.info("🔍 Detected validation-only response - skipping")
                    return {}
            
            # Validate structure
            valid_params = {}
            for param, data in parameters.items():
                if not isinstance(data, dict):
                    logger.warning(f"Invalid structure for parameter: {param}")
                    continue
                if "value" not in data:
                    logger.warning(f"Missing 'value' for parameter: {param}")
                    continue
                
                valid_params[param] = data
            
            logger.info(f"✅ Parsed {len(valid_params)} valid parameters")
            return valid_params
            
        except json.JSONDecodeError as e:
            logger.error(f"❌ Failed to parse JSON: {e}")
            logger.debug(f"Content: {content[:500]}...")
            
            # Fallback: manual extraction
            return self._manual_json_extraction(content)
        
        except Exception as e:
            logger.error(f"❌ Unexpected parsing error: {e}")
            return {}
    
    def _manual_json_extraction(self, content: str) -> Dict[str, Any]:
        """Fallback manual extraction if JSON parsing fails - FIXED"""
        logger.warning("⚠️ Using fallback extraction")
        try:
            # Try to find JSON object in content
            match = re.search(r'\{.*\}', content, re.DOTALL)
            if match:
                json_str = match.group(0)
                parameters = json.loads(json_str)
                
                if isinstance(parameters, dict):
                    # ✅ FIXED: Check for validation response here too
                    validation_keys = {'valid', 'errors', 'warnings', 'suggestions'}
                    if validation_keys.issubset(set(parameters.keys())):
                        logger.info("🔍 Fallback: Detected validation response - skipping")
                        return {}
                    
                    logger.info(f"✅ Fallback extraction: {len(parameters)} parameters")
                    return parameters
                    
        except Exception as e:
            logger.error(f"❌ Manual extraction failed: {e}")
        
        return {}
    
    # =====================================================
    # VALIDATION - ENHANCED
    # =====================================================
    async def validate_extraction(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Validate extracted parameters using AI - ENHANCED"""
        try:
            if not parameters:
                return {
                    "valid": True,
                    "errors": [],
                    "warnings": ["No parameters to validate"],
                    "suggestions": []
                }
            
            validation_prompt = f"""
Review these extracted water quality parameters for errors:

{json.dumps(parameters, indent=2)}

Check for:
1. Unrealistic values (e.g., pH > 14 or < 0, negative concentrations)
2. Missing or incorrect units
3. Inconsistent data (e.g., TDS lower than individual ions sum)
4. Typical ranges:
   - pH: 0-14
   - TDS: 0-5000 mg/L (typical drinking water)
   - Calcium: 0-500 mg/L
   - Temperature: 0-100°C

Return JSON with:
{{
  "valid": true/false,
  "errors": ["list of critical errors if any"],
  "warnings": ["list of warnings if any"],
  "suggestions": ["list of suggestions"]
}}

IMPORTANT: Return only JSON, no explanation.
"""
            
            response = await self.client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {
                        "role": "system",
                        "content": "You are a water quality data validator with expertise in chemistry."
                    },
                    {
                        "role": "user",
                        "content": validation_prompt
                    }
                ],
                temperature=0,
                max_tokens=1000
            )
            
            content = response.choices[0].message.content
            
            # ✅ IMPROVED: Don't use _parse_gpt_response for validation (causes recursion)
            # Parse directly
            validation_result = {}
            try:
                # Clean markdown
                content = content.strip()
                if content.startswith("```json"):
                    content = content[7:]
                elif content.startswith("```"):
                    content = content[3:]
                if content.endswith("```"):
                    content = content[:-3]
                content = content.strip()
                
                validation_result = json.loads(content)
            except json.JSONDecodeError as e:
                logger.warning(f"⚠️ Validation response parsing failed: {e}")
                return {
                    "valid": True,
                    "errors": [],
                    "warnings": ["Validation parsing failed"],
                    "suggestions": []
                }
            
            if not validation_result:
                return {
                    "valid": True,
                    "errors": [],
                    "warnings": ["Validation parsing failed"],
                    "suggestions": []
                }
            
            if not validation_result.get("valid", True):
                logger.warning(f"⚠️ Validation found issues: {validation_result.get('errors', [])}")
            else:
                logger.info("✅ Validation passed")
            
            return validation_result
            
        except Exception as e:
            logger.error(f"❌ Validation failed: {e}")
            return {
                "valid": True,
                "errors": [],
                "warnings": [],
                "suggestions": [],
                "note": "Validation skipped due to error"
            }
    
    # =====================================================
    # UTILS - FIXED
    # =====================================================
    def _image_to_base64(self, image: Image.Image) -> str:
        """Convert PIL Image to base64 string - FIXED"""
        try:
            if not image:
                raise ValueError("Invalid image object")
            
            buffered = BytesIO()
            
            # Convert to RGB if needed
            if image.mode not in ['RGB', 'L']:
                image = image.convert('RGB')
            
            # Save as JPEG with high quality
            image.save(buffered, format="JPEG", quality=95, optimize=True)
            
            # Get bytes
            img_bytes = buffered.getvalue()
            
            if not img_bytes:
                raise ValueError("Failed to encode image")
            
            # Encode to base64
            base64_str = base64.b64encode(img_bytes).decode('utf-8')
            
            logger.debug(f"Image encoded: {len(base64_str)} chars")
            
            return base64_str
            
        except Exception as e:
            logger.error(f"❌ Image encoding failed: {e}")
            raise ValueError(f"Failed to encode image: {str(e)}")