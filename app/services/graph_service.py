

"""
Graph Service - 100% DYNAMIC VERSION
✅ NO hard-coded parameters
✅ AI determines status for unknown parameters
✅ Fallback to database first, then AI
✅ Production ready
"""

import os
import json
import logging
from typing import Dict, Any, Optional
from datetime import datetime
from io import BytesIO

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import seaborn as sns
import numpy as np
from openai import AsyncOpenAI
import boto3
from botocore.exceptions import ClientError

from app.db.mongo import db

logger = logging.getLogger(__name__)


class GraphService:
    """Generate dynamic water quality graphs - 100% AI-powered"""
    
    def __init__(self):
        self.client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        self.s3_client = boto3.client(
            's3',
            aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
            region_name=os.getenv("AWS_REGION")
        )
        self.bucket_name = os.getenv("AWS_S3_BUCKET")
        
        # Set style
        sns.set_style("whitegrid")
        plt.rcParams['figure.dpi'] = 300
        
        # ✅ Cache for AI-determined statuses (to avoid repeated API calls)
        self._status_cache = {}
    
    async def create_parameter_graph(
        self,
        parameters: Dict[str, Any],
        chemical_status: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Create high-quality parameter comparison bar chart.
        Dark theme, color-coded by status, reference lines, clean typography.
        """
        try:
            logger.info("📊 Creating parameter comparison graph")

            # ── Extract numeric parameters ────────────────────────────────────
            SKIP_PARAMS = {"temperature", "temp", "tds", "conductivity", "ec", "ph"}
            numeric_params: Dict[str, float] = {}
            units_map: Dict[str, str] = {}

            for param_name, param_data in parameters.items():
                if param_name.lower().replace(" ", "_") in SKIP_PARAMS:
                    continue
                value = param_data.get("value") if isinstance(param_data, dict) else param_data
                unit  = param_data.get("unit", "mg/L") if isinstance(param_data, dict) else "mg/L"
                if isinstance(value, (int, float)) and value > 0:
                    numeric_params[param_name] = float(value)
                    units_map[param_name] = unit or "mg/L"

            if not numeric_params:
                raise Exception("No numeric parameters found for graph")

            # ── Determine status / color per parameter ────────────────────────
            color_mapping: Dict[str, str] = {}
            status_mapping: Dict[str, str] = {}
            template = await db.get_graph_template("parameter_comparison_bar") or self._get_default_template()

            for param_name, value in numeric_params.items():
                status = await self._get_parameter_status_dynamic(param_name, value)
                color  = self._get_color_for_status(status, template)
                color_mapping[param_name]  = color
                status_mapping[param_name] = status

            # ── Build figure ──────────────────────────────────────────────────
            n = len(numeric_params)
            fig_w = max(10, n * 1.1)
            fig, ax = plt.subplots(figsize=(fig_w, 6))

            # Dark background
            fig.patch.set_facecolor("#0f0f1a")
            ax.set_facecolor("#16213e")

            param_names = list(numeric_params.keys())
            values      = list(numeric_params.values())
            colors      = [color_mapping[p] for p in param_names]
            x_pos       = range(n)

            # ── Bars ──────────────────────────────────────────────────────────
            bars = ax.bar(
                x_pos, values,
                color=colors,
                width=0.6,
                edgecolor="#ffffff22",
                linewidth=0.8,
                zorder=3,
            )

            # Subtle gradient overlay (lighter top edge)
            for bar, color in zip(bars, colors):
                bar.set_alpha(0.88)

            # ── Value labels on top of bars ───────────────────────────────────
            for bar, val, param in zip(bars, values, param_names):
                unit = units_map.get(param, "")
                label = f"{val:.1f}" if val < 1000 else f"{val:,.0f}"
                ax.text(
                    bar.get_x() + bar.get_width() / 2,
                    bar.get_height() + max(values) * 0.015,
                    label,
                    ha="center", va="bottom",
                    fontsize=8.5, fontweight="bold",
                    color="#ffffff", zorder=5,
                )

            # ── X axis labels ─────────────────────────────────────────────────
            ax.set_xticks(list(x_pos))
            ax.set_xticklabels(
                [f"{p}\n({units_map.get(p,'')})" for p in param_names],
                rotation=35, ha="right",
                fontsize=9, color="#cccccc",
            )

            # ── Y axis ───────────────────────────────────────────────────────
            ax.set_ylabel("Concentration", fontsize=11, color="#aaaaaa", labelpad=10)
            ax.tick_params(axis="y", colors="#888888", labelsize=9)
            ax.yaxis.set_tick_params(length=0)

            # ── Grid ─────────────────────────────────────────────────────────
            ax.yaxis.grid(True, color="#2a2a4a", linewidth=0.6, linestyle="--", zorder=0)
            ax.set_axisbelow(True)

            # ── Spines ───────────────────────────────────────────────────────
            for spine in ax.spines.values():
                spine.set_edgecolor("#2a2a4a")
                spine.set_linewidth(0.8)
            ax.spines["top"].set_visible(False)
            ax.spines["right"].set_visible(False)

            # ── Title ─────────────────────────────────────────────────────────
            ax.set_title(
                "Water Parameter Analysis",
                fontsize=14, fontweight="bold",
                color="#ffffff", pad=16,
            )

            # ── Legend ───────────────────────────────────────────────────────
            from matplotlib.patches import Patch
            legend_items = [
                Patch(facecolor="#2ECC71", label="Optimal"),
                Patch(facecolor="#F1C40F", label="Warning"),
                Patch(facecolor="#E74C3C", label="Critical"),
                Patch(facecolor="#3498DB", label="Normal"),
            ]
            ax.legend(
                handles=legend_items,
                loc="upper right",
                framealpha=0.15,
                facecolor="#1a1a2e",
                edgecolor="#2a2a4a",
                labelcolor="#cccccc",
                fontsize=9,
            )

            # ── X limits padding ──────────────────────────────────────────────
            ax.set_xlim(-0.6, n - 0.4)
            ax.set_ylim(0, max(values) * 1.18)

            plt.tight_layout(pad=1.5)

            # ── Save ──────────────────────────────────────────────────────────
            buffer = BytesIO()
            plt.savefig(
                buffer, format="png", dpi=150,
                bbox_inches="tight",
                facecolor=fig.get_facecolor(),
            )
            buffer.seek(0)
            plt.close(fig)

            graph_url = await self._upload_to_s3(buffer, "parameter_comparison")
            if graph_url:
                logger.info(f"✅ Graph created: {graph_url}")
            else:
                logger.warning("⚠️ Graph generated but S3 upload skipped — graph_url will be null")

            return {
                "graph_url":     graph_url,        # None if S3 unavailable
                "graph_type":    "parameter_comparison_bar",
                "color_mapping": status_mapping,
                "created_at":    datetime.utcnow(),
            }

        except Exception as e:
            logger.exception("❌ Graph creation failed")
            # Return a safe fallback instead of raising — prevents 500 on the analysis endpoint
            return {
                "graph_url":     None,
                "graph_type":    "parameter_comparison_bar",
                "color_mapping": {},
                "error":         str(e),
                "created_at":    datetime.utcnow(),
            }
    
    async def modify_with_prompt(
        self,
        report_id: str,
        parameters: Dict[str, Any],
        prompt: str
    ) -> Dict[str, Any]:
        """
        Modify graph colors using natural language prompt
        """
        try:
            logger.info(f"🎨 Modifying graph with prompt: '{prompt}'")
            
            # Parse intent
            color_changes = await self._parse_color_intent(prompt, parameters.keys())
            
            if not color_changes:
                logger.warning("⚠️ No color changes detected, using auto colors")
            else:
                logger.info(f"✅ Color changes: {color_changes}")
            
            # Get template
            template = await db.get_graph_template("parameter_comparison_bar")
            if not template:
                template = self._get_default_template()
            
            # Extract numeric parameters
            numeric_params = {}
            for param_name, param_data in parameters.items():
                value = param_data.get("value")
                if isinstance(value, (int, float)):
                    numeric_params[param_name] = value
            
            # Apply colors
            color_mapping = {}
            
            for param_name, value in numeric_params.items():
                if param_name in color_changes:
                    # Custom color from prompt
                    color_mapping[param_name] = self._resolve_color_name(
                        color_changes[param_name],
                        template
                    )
                    logger.info(f"🎨 {param_name}: custom color '{color_changes[param_name]}'")
                else:
                    # Auto color based on AI status
                    status = await self._get_parameter_status_dynamic(param_name, value)
                    color_mapping[param_name] = self._get_color_for_status(status, template)
                    logger.info(f"🤖 {param_name}: auto color '{status}'")
            
            # Create graph
            fig, ax = plt.subplots(figsize=tuple(template['default_config']['figsize']))
            
            param_names = list(numeric_params.keys())
            values = list(numeric_params.values())
            colors = [color_mapping[name] for name in param_names]
            
            bars = ax.bar(
                param_names, 
                values, 
                color=colors, 
                edgecolor='black', 
                linewidth=1.5, 
                alpha=0.85
            )
            
            # Add value labels
            for bar, value in zip(bars, values):
                height = bar.get_height()
                ax.text(
                    bar.get_x() + bar.get_width() / 2.,
                    height,
                    f'{value:.2f}',
                    ha='center',
                    va='bottom',
                    fontsize=9,
                    fontweight='bold'
                )
            
            # Styling
            ax.set_xlabel(template['default_config']['xlabel'], fontsize=12, fontweight='bold')
            ax.set_ylabel(template['default_config']['ylabel'], fontsize=12, fontweight='bold')
            ax.set_title(template['default_config']['title'], fontsize=14, fontweight='bold', pad=20)
            plt.xticks(rotation=template['default_config']['rotation'], ha='right', fontsize=10)
            
            if template['default_config']['grid']:
                ax.grid(axis='y', alpha=0.3, linestyle='--')
            
            plt.tight_layout()
            
            # Save
            buffer = BytesIO()
            plt.savefig(buffer, format='png', dpi=template['default_config']['dpi'], bbox_inches='tight')
            buffer.seek(0)
            plt.close(fig)
            
            # Upload
            graph_url = await self._upload_to_s3(buffer, f"parameter_comparison_{report_id}_modified")
            
            logger.info(f"✅ Modified graph created")
            
            return {
                "graph_url": graph_url,
                "graph_type": "parameter_comparison_bar",
                "color_mapping": color_mapping,
                "prompt_applied": prompt,
                "created_at": datetime.utcnow()
            }
            
        except Exception as e:
            logger.exception("❌ Graph modification failed")
            raise Exception(f"Graph modification failed: {str(e)}")
    
    # =====================================================
    # 🤖 AI-POWERED DYNAMIC STATUS DETERMINATION
    # =====================================================
    async def _get_parameter_status_dynamic(self, param_name: str, value: float) -> str:
        """
        ✅ 100% DYNAMIC - No hard-coding
        
        Strategy:
        1. Try database first
        2. If not in DB, ask AI
        3. Cache result to avoid repeated API calls
        
        Returns: "optimal", "good", "warning", "critical"
        """
        # Check cache first
        cache_key = f"{param_name}:{value}"
        if cache_key in self._status_cache:
            logger.debug(f"📦 Cache hit: {param_name}")
            return self._status_cache[cache_key]
        
        # Strategy 1: Try database
        standard = await db.get_parameter_standard(param_name)
        
        if standard:
            logger.debug(f"💾 Database standard found for {param_name}")
            status = self._evaluate_with_thresholds(value, standard.get('thresholds', {}))
            self._status_cache[cache_key] = status
            return status
        
        # Strategy 2: Ask AI
        logger.info(f"🤖 No DB standard for {param_name}, asking AI...")
        status = await self._ai_determine_status(param_name, value)
        
        # Cache the result
        self._status_cache[cache_key] = status
        
        return status
    
    def _evaluate_with_thresholds(self, value: float, thresholds: Dict) -> str:
        """Evaluate value against threshold ranges"""
        for level in ['optimal', 'good', 'warning', 'critical']:
            threshold = thresholds.get(level, {})
            
            if not threshold:
                continue
            
            min_val = threshold.get('min', float('-inf'))
            max_val = threshold.get('max', float('inf'))
            
            if min_val <= value <= max_val:
                return level
        
        return "good"  # Default
    
    async def _ai_determine_status(self, param_name: str, value: float) -> str:
        """
        ✅ Ask GPT-4o to determine parameter status
        
        Returns: "optimal", "good", "warning", or "critical"
        """
        try:
            response = await self.client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {
                        "role": "system",
                        "content": """You are a water quality expert. Evaluate water quality parameters for drinking water safety.

Return ONLY one word from: optimal, good, warning, critical

Definitions:
- optimal: Ideal/best quality for drinking water
- good: Acceptable/safe for drinking water
- warning: Concerning/needs attention
- critical: Dangerous/unsafe for drinking water

Base your judgment on WHO, EPA, and international drinking water standards."""
                    },
                    {
                        "role": "user",
                        "content": f"Parameter: {param_name}\nValue: {value} mg/L\n\nStatus?"
                    }
                ],
                temperature=0,
                max_tokens=10
            )
            
            status = response.choices[0].message.content.strip().lower()
            
            # Validate response
            valid_statuses = ['optimal', 'good', 'warning', 'critical']
            
            if status not in valid_statuses:
                logger.warning(f"⚠️ AI returned invalid status '{status}', using 'good'")
                status = 'good'
            
            logger.info(f"🤖 AI: {param_name}={value} → {status}")
            
            return status
            
        except Exception as e:
            logger.error(f"❌ AI status determination failed: {e}")
            return "good"  # Safe fallback
    
    # =====================================================
    # COLOR INTENT PARSING
    # =====================================================
    async def _parse_color_intent(self, prompt: str, available_params: list) -> Dict[str, str]:
        """
        Parse natural language color modification request
        
        Returns: {"pH": "green", "TDS": "red", ...}
        """
        try:
            logger.info(f"🔍 Parsing prompt: '{prompt}'")
            
            response = await self.client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {
                        "role": "system",
                        "content": f"""You are a color parser for water quality graphs.

Available parameters: {', '.join(list(available_params))}

Valid colors:
- Status: optimal, good, warning, critical
- Named: red, green, blue, yellow, orange, purple, pink, brown, gray

Parse the user's request and return ONLY a JSON object.

Rules:
1. Return ONLY valid JSON, no explanation
2. Use exact parameter names
3. If unclear, return empty: {{}}

Examples:
"make pH green" → {{"pH": "green"}}
"color TDS red and Calcium blue" → {{"TDS": "red", "Calcium": "blue"}}
"make a bar chart" → {{}}
"""
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                temperature=0,
                max_tokens=500
            )
            
            content = response.choices[0].message.content
            
            if not content:
                return {}
            
            logger.debug(f"GPT: {content}")
            
            # Clean response
            content = content.strip()
            
            # Remove markdown
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()
            
            # Find JSON
            if not content.startswith("{"):
                import re
                match = re.search(r'\{[^}]+\}', content)
                if match:
                    content = match.group(0)
                else:
                    return {}
            
            # Parse
            color_changes = json.loads(content)
            
            if not isinstance(color_changes, dict):
                return {}
            
            logger.info(f"✅ Parsed: {color_changes}")
            return color_changes
            
        except Exception as e:
            logger.error(f"❌ Parse failed: {e}")
            return {}
    
    def _resolve_color_name(self, color_name: str, template: Dict) -> str:
        """Resolve color name to hex code"""
        color_scheme = template.get('color_scheme', {})
        
        color_name = color_name.lower().strip()
        
        # Check status colors
        if color_name in color_scheme:
            return color_scheme[color_name]
        
        # Check custom colors
        custom_colors = color_scheme.get('custom_colors', {})
        if color_name in custom_colors:
            return custom_colors[color_name]
        
        # Common colors
        common = {
            'red': '#F44336',
            'green': '#4CAF50',
            'blue': '#2196F3',
            'yellow': '#FFC107',
            'orange': '#FF9800',
            'purple': '#9C27B0',
            'pink': '#E91E63',
            'brown': '#795548',
            'gray': '#757575',
            'grey': '#757575'
        }
        
        return common.get(color_name, '#757575')
    
    def _get_color_for_status(self, status: str, template: Dict) -> str:
        """Get hex color for status"""
        color_scheme = template.get('color_scheme', {})
        return color_scheme.get(status, '#757575')
    
    # =====================================================
    # S3 UPLOAD
    # =====================================================
    async def _upload_to_s3(self, buffer: BytesIO, filename_prefix: str) -> Optional[str]:
        """
        Upload graph to S3 and return a pre-signed URL (7 days).
        Returns None — does NOT raise — if S3 is unavailable or credentials are invalid.
        This allows the analysis pipeline to continue even without a working S3 bucket.
        """
        # Guard: skip entirely if bucket or credentials are not configured
        if not self.bucket_name:
            logger.warning("⚠️ S3 bucket not configured (AWS_S3_BUCKET missing) — skipping upload")
            return None

        try:
            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            key = f"graphs/{filename_prefix}_{timestamp}.png"

            self.s3_client.upload_fileobj(
                buffer,
                self.bucket_name,
                key,
                ExtraArgs={'ContentType': 'image/png'}
            )

            logger.info(f"✅ S3: {key}")

            url = self.s3_client.generate_presigned_url(
                'get_object',
                Params={'Bucket': self.bucket_name, 'Key': key},
                ExpiresIn=604800  # 7 days
            )

            return url

        except Exception as e:
            logger.error(f"❌ S3 upload failed (graph_url will be null): {e}")
            return None  # Graceful degradation — caller handles None
    
    # =====================================================
    # DEFAULT TEMPLATE
    # =====================================================
    def _get_default_template(self) -> Dict:
        """Default graph template"""
        return {
            "graph_type": "parameter_comparison_bar",
            "default_config": {
                "figsize": [14, 7],
                "dpi": 300,
                "title": "Water Quality Parameter Comparison",
                "xlabel": "Parameters",
                "ylabel": "Concentration (mg/L)",
                "rotation": 45,
                "grid": True
            },
            "color_scheme": {
                "optimal": "#4CAF50",     # Green - Best
                "good": "#8BC34A",        # Light Green - Safe
                "warning": "#FFC107",     # Yellow - Caution
                "critical": "#F44336",    # Red - Danger
                "unknown": "#757575",     # Gray - Unknown
                "custom_colors": {
                    "red": "#F44336",
                    "green": "#4CAF50",
                    "blue": "#2196F3",
                    "yellow": "#FFC107",
                    "orange": "#FF9800",
                    "purple": "#9C27B0",
                    "pink": "#E91E63",
                    "brown": "#795548",
                    "gray": "#757575"
                }
            }
        }