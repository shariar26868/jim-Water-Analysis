"""
Saturation Analysis Service  — v2
===================================
Accepts fully-resolved AI-server payload.
No DB fetch for water params (comes inline).
Dynamic base_water_parameters key mapping.
All saturation index details saved (Phase, SI, log IAP, log K, formula).
3 public methods:
  run_analysis(request_dict)   → full pipeline
  switch_salt(run_id, salt_id) → re-graph from saved DB data
  get_available_salts()        → PHREEQC mineral list (cached)
"""

import io
import logging
import math
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import boto3
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from botocore.exceptions import BotoCoreError, ClientError

from app.db.mongo import db
from app.services.phreeqc_service import PHREEQCService
from app.services.calculation_service import CalculationService
from app.services.cooling_tower_service import CoolingTowerService

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# DYNAMIC WATER PARAMETER KEY MAPPER
# Maps any OCR-extracted key → PHREEQC internal ion key
# ─────────────────────────────────────────────────────────────────────────────
_PARAM_ALIAS: Dict[str, str] = {
    # Calcium
    "calcium": "Ca", "ca": "Ca",
    # Magnesium
    "magnesium": "Mg", "mg": "Mg",
    # Sodium
    "sodium": "Na", "na": "Na",
    # Potassium
    "potassium": "K", "k": "K",
    # Chloride
    "chloride": "Cl", "cl": "Cl",
    # Sulfate / Sulphate
    "sulfate": "SO4", "sulphate": "SO4", "so4": "SO4",
    # Alkalinity / Bicarbonate
    "alkalinity": "HCO3", "bicarbonate": "HCO3", "hco3": "HCO3",
    "total_alkalinity": "HCO3",
    # Silica
    "silica": "SiO2", "sio2": "SiO2", "silicon": "SiO2",
    # Barium
    "barium": "Ba", "ba": "Ba",
    # Strontium
    "strontium": "Sr", "sr": "Sr",
    # Iron
    "iron": "Fe", "fe": "Fe",
    # pH
    "ph": "pH",
    # Temperature
    "temperature": "Temperature", "temp": "Temperature",
    # Nitrate
    "nitrate": "NO3", "no3": "NO3",
    # Fluoride
    "fluoride": "F", "f": "F",
    # Phosphate
    "phosphate": "PO4", "po4": "PO4",
    # Manganese
    "manganese": "Mn", "mn": "Mn",
}

# pH adjustment rules per chemical
_PH_RULES: Dict[str, Dict[str, float]] = {
    "H2SO4": {"HCO3": -1.00, "SO4": +1.00},
    "HCL":   {"HCO3": -1.37, "Cl":  +0.97},
    "NAOH":  {"HCO3": +1.25, "Na":  +0.57},
}

# Colour hex values
_COLOUR_HEX = {"green": "#2ECC71", "yellow": "#F1C40F", "red": "#E74C3C", "error": "#BDC3C7"}


def _map_water_params(raw: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convert dynamic OCR keys → internal PHREEQC ion keys.
    Handles nested {value, unit, detection_limit} dicts.
    Skips non-numeric / zero-value entries.
    """
    out: Dict[str, Any] = {}
    for key, val in raw.items():
        norm = key.lower().replace(" ", "_").replace("-", "_")
        ion = _PARAM_ALIAS.get(norm)
        if ion is None:
            # try partial match
            for alias, mapped in _PARAM_ALIAS.items():
                if alias in norm or norm in alias:
                    ion = mapped
                    break
        if ion is None:
            continue

        # Extract numeric value
        if isinstance(val, dict):
            numeric = val.get("value")
        elif isinstance(val, (int, float)):
            numeric = val
        else:
            continue

        if numeric is None:
            continue
        try:
            numeric = float(numeric)
        except (TypeError, ValueError):
            continue

        out[ion] = numeric

    return out


def _apply_ph_adjustment(params: Dict[str, Any], chemical: Optional[str]) -> Dict[str, Any]:
    """Adjust alkalinity + counterion based on pH chemical. Dose is implicit in fixed_ph logic."""
    if not chemical:
        return dict(params)
    rules = _PH_RULES.get(chemical.upper().replace("-", "").replace("_", ""))
    if not rules:
        logger.warning(f"Unknown pH chemical '{chemical}', skipping adjustment")
        return dict(params)
    adjusted = dict(params)
    for ion, factor in rules.items():
        current = float(adjusted.get(ion, 0.0))
        # Apply a nominal 1-unit adjustment signal (actual dose handled by fixed_ph override)
        adjusted[ion] = max(0.0, current + factor)
    return adjusted


def _color_code(si: float, max_si: float, band_lower: float, band_upper: float) -> str:
    if si < max_si:
        return "green"
    if si <= band_upper:
        return "yellow"
    return "red"


def _parse_thresholds(raw_material_chemistry: Optional[Dict]) -> Dict[str, float]:
    """Extract color band thresholds from raw_material_chemistry."""
    if not raw_material_chemistry:
        return {"max_si_at_dose": 0.0, "band_lower": 0.0, "band_upper": 0.5}

    def _to_float(v, default=0.0):
        try:
            return float(v)
        except (TypeError, ValueError):
            return default

    return {
        "max_si_at_dose": 0.0,
        "band_lower": _to_float(raw_material_chemistry.get("bandLowerCushion"), 0.0),
        "band_upper": _to_float(raw_material_chemistry.get("bandUpperCushion"), 0.5),
    }


# ─────────────────────────────────────────────────────────────────────────────
# MAIN SERVICE
# ─────────────────────────────────────────────────────────────────────────────

class SaturationService:

    COLOUR_MAP = _COLOUR_HEX

    def __init__(self):
        self.phreeqc = PHREEQCService()
        # Support both AWS_S3_BUCKET_NAME and AWS_S3_BUCKET (common naming variants)
        self.s3_bucket  = os.getenv("AWS_S3_BUCKET_NAME") or os.getenv("AWS_S3_BUCKET", "")
        self.s3_region  = os.getenv("AWS_REGION", "us-east-1")
        self.s3_prefix  = os.getenv("AWS_S3_SATURATION_PREFIX", "saturation-graphs/")
        self._s3 = None

    def _get_s3(self):
        if self._s3 is None:
            self._s3 = boto3.client(
                "s3",
                region_name=self.s3_region,
                aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
                aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
            )
        return self._s3

    # ── STEP: build grid ─────────────────────────────────────────────────────
    @staticmethod
    def _build_grid(
        coc_min: float, coc_max: float, coc_interval: float,
        temp_min: float, temp_max: float, temp_interval: float,
        temp_unit: str, ph_mode: str, fixed_ph: Optional[float], base_ph: float,
    ) -> List[Dict[str, float]]:
        def f2c(f): return round((f - 32) * 5 / 9, 2)

        coc_vals, c = [], coc_min
        while c <= coc_max + 1e-9:
            coc_vals.append(round(c, 4)); c += coc_interval

        temp_vals, t = [], temp_min
        while t <= temp_max + 1e-9:
            temp_vals.append(f2c(t) if temp_unit.upper() == "F" else round(t, 2))
            t += temp_interval

        use_fixed = ph_mode.lower() == "fixed" and fixed_ph is not None
        grid = []
        for coc in coc_vals:
            for temp in temp_vals:
                grid.append({"CoC": coc, "temp": temp, "pH": fixed_ph if use_fixed else base_ph})

        logger.info(f"Grid: {len(coc_vals)} CoC × {len(temp_vals)} Temp = {len(grid)} points")
        return grid

    # ── STEP: run PHREEQC + color code ───────────────────────────────────────
    async def _run_and_color(
        self,
        mapped_params: Dict[str, Any],
        grid: List[Dict[str, float]],
        salt_id: Optional[str],
        salts_of_interest: Optional[List[str]],
        thresholds: Dict[str, float],
        balance_cation: str,
        balance_anion: str,
    ) -> Tuple[List[Dict[str, Any]], str]:

        # Select database
        coc_vals  = [p["CoC"]  for p in grid]
        temp_vals = [p["temp"] for p in grid]
        ph_vals   = [p["pH"]   for p in grid]

        database = self.phreeqc.select_database(
            mapped_params,
            ph_range=(min(ph_vals), max(ph_vals)),
            coc_range=(min(coc_vals), max(coc_vals)),
            temp_range=(min(temp_vals), max(temp_vals)),
        )
        db_name = os.path.basename(database)

        # Ion balance
        try:
            balanced = await self.phreeqc.ion_balance(
                mapped_params, cation_ion=balance_cation,
                anion_ion=balance_anion, database=database,
            )
        except Exception as e:
            logger.warning(f"Ion balance failed ({e}), using unbalanced params")
            balanced = mapped_params

        # Batch PHREEQC
        raw_results = await self.phreeqc.run_batch_solution_spread(balanced, grid, database)

        # Determine which salt to use for color coding
        color_salt = salt_id or (salts_of_interest[0] if salts_of_interest else None)

        colored: List[Dict[str, Any]] = []
        for res in raw_results:
            # Build full SI detail dict — normalize mineral names to title-case for consistency
            si_detail: Dict[str, Any] = {}
            for item in res.get("saturation_indices", []):
                if isinstance(item, dict):
                    name = item.get("mineral_name", "")
                    si_detail[name] = {
                        "SI":              round(item.get("si_value", 0.0), 4),
                        "log_IAP":         item.get("log_IAP"),
                        "log_K":           item.get("log_K"),
                        "phase":           item.get("phase"),
                        "chemical_formula": item.get("chemical_formula"),
                    }

            # Case-insensitive lookup helper
            def _find_si(si_dict: Dict, target: Optional[str]) -> Optional[float]:
                if not target:
                    return None
                # exact match first
                if target in si_dict:
                    return si_dict[target].get("SI")
                # case-insensitive fallback
                target_lower = target.lower()
                for k, v in si_dict.items():
                    if k.lower() == target_lower:
                        return v.get("SI")
                return None

            # Color code based on selected salt (case-insensitive)
            selected_si = _find_si(si_detail, color_salt)
            if selected_si is not None:
                color = _color_code(
                    selected_si,
                    thresholds["max_si_at_dose"],
                    thresholds["band_lower"],
                    thresholds["band_upper"],
                )
            else:
                color = "green"  # no salt selected → neutral

            colored.append({
                "_grid_CoC":              res.get("_grid_CoC", 0.0),
                "_grid_temp":             res.get("_grid_temp", 0.0),   # always °C
                "_grid_pH":               res.get("_grid_pH", 0.0),
                "saturation_indices":     si_detail,
                "description_of_solution": res.get("description_of_solution"),
                "color_code":             color,
                "ionic_strength":         res.get("ionic_strength", 0.0),
                "charge_balance_error_pct": res.get("charge_balance_error_pct", 0.0),
            })

        return colored, db_name

    # ── STEP: generate 3D graph ───────────────────────────────────────────────
    def _generate_graph(
        self,
        results: List[Dict[str, Any]],
        salt_id: Optional[str],
        run_id: str,
        temp_unit: str,
    ) -> bytes:
        display_salt = salt_id or "All Salts"

        # Case-insensitive salt lookup helper
        def _get_si_for_salt(si_dict: Dict, target: str) -> Optional[float]:
            if target in si_dict:
                val = si_dict[target]
                return val.get("SI") if isinstance(val, dict) else float(val)
            target_lower = target.lower()
            for k, v in si_dict.items():
                if k.lower() == target_lower:
                    return v.get("SI") if isinstance(v, dict) else float(v)
            return None

        # Filter points that have SI for the selected salt
        if salt_id:
            valid = [r for r in results if _get_si_for_salt(r["saturation_indices"], salt_id) is not None]
        else:
            valid = results

        if not valid:
            raise ValueError("No valid PHREEQC results to plot")

        x_vals = np.array([r["_grid_CoC"]  for r in valid])
        y_vals = np.array([r["_grid_temp"] for r in valid])  # °C stored

        if salt_id:
            z_vals = np.array([_get_si_for_salt(r["saturation_indices"], salt_id) for r in valid])
        else:
            # Use first available salt
            first_salt = next(iter(valid[0]["saturation_indices"]), None)
            z_vals = np.array([
                r["saturation_indices"].get(first_salt, {}).get("SI", 0.0) for r in valid
            ])

        colors = [self.COLOUR_MAP.get(r["color_code"], "#BDC3C7") for r in valid]

        # Convert temp for display label
        y_label = "Temperature (°C)"
        if temp_unit.upper() == "F":
            y_display = np.array([(t * 9/5) + 32 for t in y_vals])
            y_label = "Temperature (°F)"
        else:
            y_display = y_vals

        fig = plt.figure(figsize=(13, 8), facecolor="#1A1A2E")
        ax  = fig.add_subplot(111, projection="3d", facecolor="#16213E")

        unique_x = sorted(set(x_vals))
        unique_y = sorted(set(y_display))
        dx = max(0.3, (max(unique_x) - min(unique_x)) / max(len(unique_x), 1) * 0.7) if len(unique_x) > 1 else 0.5
        dy = max(1.5, (max(unique_y) - min(unique_y)) / max(len(unique_y), 1) * 0.7) if len(unique_y) > 1 else 5.0

        for xi, yi, zi, color in zip(x_vals, y_display, z_vals, colors):
            dz = abs(zi) if zi != 0 else 0.01
            z_bottom = min(zi, 0.0)
            ax.bar3d(xi - dx/2, yi - dy/2, z_bottom, dx, dy, dz,
                     color=color, alpha=0.85, shade=True)

        # SI=0 reference plane
        if x_vals.size and y_display.size:
            xx = np.linspace(x_vals.min() - dx, x_vals.max() + dx, 2)
            yy = np.linspace(y_display.min() - dy, y_display.max() + dy, 2)
            XX, YY = np.meshgrid(xx, yy)
            ax.plot_surface(XX, YY, np.zeros_like(XX), alpha=0.12, color="white")

        ax.set_xlabel("Cycles of Concentration", color="white", labelpad=12, fontsize=10)
        ax.set_ylabel(y_label,                   color="white", labelpad=12, fontsize=10)
        ax.set_zlabel(f"SI — {display_salt}",    color="white", labelpad=12, fontsize=10)
        ax.tick_params(colors="white", labelsize=8)
        for pane in (ax.xaxis.pane, ax.yaxis.pane, ax.zaxis.pane):
            pane.fill = False
            pane.set_edgecolor("#444466")
        ax.grid(True, color="#333355", linewidth=0.4)
        ax.set_title(f"Saturation Analysis — {display_salt}\n(Run: {run_id})",
                     color="white", fontsize=13, fontweight="bold", pad=18)

        from matplotlib.patches import Patch
        ax.legend(
            handles=[
                Patch(facecolor=_COLOUR_HEX["green"],  label="Protected"),
                Patch(facecolor=_COLOUR_HEX["yellow"], label="Caution"),
                Patch(facecolor=_COLOUR_HEX["red"],    label="Scale Risk"),
            ],
            loc="upper left", facecolor="#1A1A2E", edgecolor="#444466",
            labelcolor="white", fontsize=9,
        )
        ax.view_init(elev=25, azim=225)
        fig.tight_layout()

        buf = io.BytesIO()
        plt.savefig(buf, format="png", dpi=150, bbox_inches="tight",
                    facecolor=fig.get_facecolor())
        plt.close(fig)
        buf.seek(0)
        return buf.read()

    # ── STEP: upload to S3 ───────────────────────────────────────────────────
    def _upload_s3(self, png: bytes, run_id: str, suffix: str = "") -> str:
        if not self.s3_bucket:
            logger.warning("AWS_S3_BUCKET not set — skipping S3 upload")
            return f"local://{run_id}{suffix}.png"
        key = f"{self.s3_prefix}{run_id}{suffix}.png"
        try:
            s3 = self._get_s3()
            s3.put_object(
                Bucket=self.s3_bucket, Key=key,
                Body=png, ContentType="image/png",
            )
            # Generate presigned URL (7 days = 604800 seconds)
            url = s3.generate_presigned_url(
                "get_object",
                Params={"Bucket": self.s3_bucket, "Key": key},
                ExpiresIn=604800,
            )
            logger.info(f"Graph uploaded → presigned URL generated for {key}")
            return url
        except (BotoCoreError, ClientError) as e:
            logger.error(f"S3 upload failed: {e} — returning placeholder URL")
            return f"s3-upload-failed://{run_id}{suffix}.png"

    # ── STEP: build graph_data JSON (for frontend 3D renderer) ───────────────
    @staticmethod
    def _build_graph_data(
        results: List[Dict[str, Any]],
        salt_id: Optional[str],
        temp_unit: str,
    ) -> Dict[str, Any]:
        """
        Build Plotly-ready 3D bar chart data.
        Frontend can render this directly with Plotly or Three.js.

        Structure:
          - bars[]         → one entry per grid point, with x/y/z + color + click_data (ALL SI values)
          - plotly_traces  → ready-to-use Plotly trace objects (mesh3d + hover scatter)
          - axes           → axis labels and ranges
          - color_map      → hex colors for green/yellow/red
          - color_labels   → human-readable label per color
        """
        temp_label = f"Temperature ({'°F' if temp_unit.upper() == 'F' else '°C'})"

        # ── Color labels (defined FIRST — used in legend + click_data below) ──
        color_labels = {
            "green":  "Protected (Green)",
            "yellow": "Caution (Yellow)",
            "red":    "Scale Risk (Red)",
            "error":  "No Data",
        }

        # ── Helper: resolve SI value case-insensitively ──────────────────
        def _get_si(si_dict: Dict, target: Optional[str]) -> Optional[float]:
            if not target:
                return None
            if target in si_dict:
                v = si_dict[target]
                return v.get("SI") if isinstance(v, dict) else float(v)
            tl = target.lower()
            for k, v in si_dict.items():
                if k.lower() == tl:
                    return v.get("SI") if isinstance(v, dict) else float(v)
            return None

        # ── Build bars ───────────────────────────────────────────────────
        bars = []
        for r in results:
            temp_display = round(
                (r["_grid_temp"] * 9/5 + 32) if temp_unit.upper() == "F" else r["_grid_temp"], 1
            )
            si_val = _get_si(r["saturation_indices"], salt_id)

            # Full SI data for ALL minerals at this grid point
            all_si = {
                mineral: (
                    {
                        "SI":               info.get("SI"),
                        "log_IAP":          info.get("log_IAP"),
                        "log_K":            info.get("log_K"),
                        "chemical_formula": info.get("chemical_formula"),
                        "phase":            info.get("phase"),
                    }
                    if isinstance(info, dict) else {"SI": float(info)}
                )
                for mineral, info in r["saturation_indices"].items()
            }

            desc = r.get("description_of_solution") or {}

            bars.append({
                # ── Plotly 3D axes ──
                "x":         r["_grid_CoC"],   # X-axis: Cycles of Concentration
                "y":         si_val,            # Z-axis / bar height: SI value
                "z":         temp_display,      # Y-axis: Temperature
                # ── Color ──
                "color":     r["color_code"],
                "color_hex": _COLOUR_HEX.get(r["color_code"], "#BDC3C7"),
                # ── click_data: everything frontend needs when user clicks a bar ──
                "click_data": {
                    "CoC":              r["_grid_CoC"],
                    "temperature":      temp_display,
                    "temperature_unit": "°F" if temp_unit.upper() == "F" else "°C",
                    "pH":               r["_grid_pH"],
                    "selected_salt":    salt_id,
                    "SI":               si_val,
                    "status":           color_labels.get(r["color_code"], r["color_code"]),
                    "ionic_strength":   r.get("ionic_strength"),
                    "charge_balance_error_pct": r.get("charge_balance_error_pct"),
                    "density":          desc.get("density"),
                    "activity_of_water": desc.get("activity_of_water"),
                    # Every mineral/salt SI at this grid point
                    "all_saturation_indices": all_si,
                },
                # ── Legacy tooltip alias (backward compat) ──
                "tooltip": {
                    "CoC":              r["_grid_CoC"],
                    "temperature":      f"{temp_display} {'°F' if temp_unit.upper() == 'F' else '°C'}",
                    "pH":               r["_grid_pH"],
                    "SI":               si_val,
                    "salt":             salt_id,
                    "ionic_strength":   r.get("ionic_strength"),
                    "charge_balance_error_pct": r.get("charge_balance_error_pct"),
                    "density":          desc.get("density"),
                    "activity_of_water": desc.get("activity_of_water"),
                    "all_saturation_indices": all_si,
                },
            })

        # ── Axis range data (defined here — BEFORE bar dimension calc below) ──
        unique_coc  = sorted(set(b["x"] for b in bars))
        unique_temp = sorted(set(b["z"] for b in bars))

        # ── Build Plotly traces — true 3D bars using mesh3d ─────────────
        # Each bar = one rectangular box (8 vertices, 12 triangles)
        def _make_bar_mesh(x_center, z_center, y_top, color_hex, dx=0.4, dz=4.0):
            """Create a single 3D bar as mesh3d vertices."""
            x0, x1 = x_center - dx/2, x_center + dx/2
            z0, z1 = z_center - dz/2, z_center + dz/2
            y0, y1 = min(y_top, 0.0), max(y_top, 0.0)

            # 8 corners of the box
            vx = [x0,x1,x1,x0, x0,x1,x1,x0]
            vy = [y0,y0,y0,y0, y1,y1,y1,y1]
            vz = [z0,z0,z1,z1, z0,z0,z1,z1]

            # 12 triangles (2 per face × 6 faces)
            i = [0,0,1,1,2,2,3,3,4,4,0,0]
            j = [1,2,2,5,3,6,0,7,5,6,4,5]
            k = [2,3,5,6,6,7,7,4,6,7,5,1]

            return {
                "type":       "mesh3d",
                "x": vx, "y": vy, "z": vz,
                "i": i, "j": j, "k": k,
                "color":      color_hex,
                "opacity":    0.85,
                "flatshading": True,
                "showscale":  False,
                "lighting":   {"ambient": 0.6, "diffuse": 0.8, "specular": 0.3},
            }

        # Bar dimensions based on grid spacing (unique_* defined above)
        if len(unique_coc) > 1:
            dx = (max(unique_coc) - min(unique_coc)) / len(unique_coc) * 0.7
        else:
            dx = 0.4

        if len(unique_temp) > 1:
            dz = (max(unique_temp) - min(unique_temp)) / len(unique_temp) * 0.7
        else:
            dz = 4.0

        plotly_traces = []

        # Add one invisible scatter3d per color group for the legend
        legend_added = set()
        for bar in bars:
            color = bar["color"]
            if color not in legend_added:
                plotly_traces.append({
                    "type":   "scatter3d",
                    "mode":   "markers",
                    "name":   color_labels.get(color, color),
                    "x":      [bar["x"]],
                    "y":      [bar["z"]],
                    "z":      [bar["y"] if bar["y"] is not None else 0],
                    "marker": {"size": 0.1, "color": _COLOUR_HEX.get(color, "#BDC3C7")},
                    "showlegend": True,
                    "hoverinfo": "skip",
                })
                legend_added.add(color)

        # Add mesh3d bar for each grid point
        for bar in bars:
            si = bar["y"] if bar["y"] is not None else 0.0
            mesh = _make_bar_mesh(
                x_center=bar["x"],
                z_center=bar["z"],
                y_top=si,
                color_hex=_COLOUR_HEX.get(bar["color"], "#BDC3C7"),
                dx=dx,
                dz=dz,
            )
            # Attach to traces
            mesh["showlegend"] = False
            plotly_traces.append(mesh)

            # Hover/click point at bar top — carries full click_data
            cd = bar["click_data"]
            plotly_traces.append({
                "type":       "scatter3d",
                "mode":       "markers",
                "x":          [bar["x"]],
                "y":          [bar["z"]],
                "z":          [si],
                "marker":     {"size": 8, "color": _COLOUR_HEX.get(bar["color"], "#BDC3C7"), "opacity": 0.01},
                "text":       [si],
                "customdata": [cd],   # full click_data attached here
                "hovertemplate": (
                    f"<b>CoC:</b> {cd['CoC']}<br>"
                    f"<b>Temp:</b> {cd['temperature']} {cd['temperature_unit']}<br>"
                    f"<b>pH:</b> {cd['pH']}<br>"
                    f"<b>SI ({salt_id}):</b> {si:.4f}<br>"
                    f"<b>Status:</b> {cd['status']}"
                    "<extra></extra>"
                ),
                "showlegend": False,
            })

        # ── Plotly layout ────────────────────────────────────────────────
        x_vals = [b["x"] for b in bars]
        z_vals = [b["z"] for b in bars]
        y_vals = [b["y"] for b in bars if b["y"] is not None]

        plotly_layout = {
            "title": f"Saturation Analysis — {salt_id or 'All Salts'}",
            "scene": {
                "xaxis": {
                    "title": "Cycles of Concentration",
                    "range": [min(x_vals) - 0.5, max(x_vals) + 0.5] if x_vals else [0, 10],
                },
                "yaxis": {
                    "title": temp_label,
                    "range": [min(z_vals) - 5, max(z_vals) + 5] if z_vals else [0, 200],
                },
                "zaxis": {
                    "title": f"Saturation Index ({salt_id or 'SI'})",
                    "range": [
                        min(y_vals) - 0.5 if y_vals else -2,
                        max(y_vals) + 0.5 if y_vals else 2,
                    ],
                },
                "bgcolor": "#16213E",
                "xaxis_gridcolor": "#333355",
                "yaxis_gridcolor": "#333355",
                "zaxis_gridcolor": "#333355",
            },
            "paper_bgcolor": "#1A1A2E",
            "font":   {"color": "white"},
            "legend": {"bgcolor": "#1A1A2E", "bordercolor": "#444466"},
            "margin": {"l": 0, "r": 0, "t": 40, "b": 0},
        }

        # (color_labels and unique_coc/unique_temp already defined above)

        return {
            "type":          "3d_bar",
            "salt_id":       salt_id,
            "temp_unit":     temp_unit,
            "total_points":  len(bars),
            "axes": {
                "x": {"label": "Cycles of Concentration", "values": unique_coc},
                "y": {"label": f"Saturation Index ({salt_id or 'SI'})", "unit": "SI"},
                "z": {"label": temp_label, "values": unique_temp},
            },
            "bars":           bars,
            "plotly_traces":  plotly_traces,
            "plotly_layout":  plotly_layout,
            "color_map":      _COLOUR_HEX,
            "color_labels":   color_labels,
        }

    # ── STEP: enrich each grid point with all calculated values ─────────────
    @staticmethod
    async def _enrich_grid_points(
        results: List[Dict[str, Any]],
        base_water_parameters: Dict[str, Any],
        req: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """
        For each grid point, calculate:
          - Deposition indices (LSI, RSI, PSI, Larson-Skold, Stiff & Davis, CCPP)
          - Blowdown & Makeup rates
          - Chemical feedrate & cost
          - Corrosion rates (per metal in asset_info.systemMetallurgy)
        """
        calc_svc = CalculationService()
        ct_svc   = CoolingTowerService()

        asset_info       = req.get("asset_info") or {}
        raw_mat          = req.get("raw_material_chemistry") or {}
        product_blend    = req.get("product_blend") or {}
        dosage_ppm       = float(req.get("dosage_ppm", 2.0))
        temp_unit        = req.get("temp_unit", "C")

        # Cooling tower params from asset_info
        recirc_rate_gpm  = float(asset_info.get("recirculationRate") or 0)
        hot_temp_f       = float(asset_info.get("hotWaterTempF") or 0)
        cold_temp_f      = float(asset_info.get("coldWaterTempF") or 0)
        wet_bulb_f       = float(asset_info.get("wetBulbTempF") or 0)
        drift_pct        = float(asset_info.get("driftPercent") or 0.1)
        evap_factor      = float(asset_info.get("evaporationFactorPercent") or 85.0)
        metallurgy       = asset_info.get("systemMetallurgy") or []

        # Product cost ($/lb or $/kg)
        product_cost_per_lb = float(product_blend.get("costPerLb") or 0)
        product_name        = product_blend.get("productName") or "Product"

        enriched = []
        for r in results:
            coc      = r["_grid_CoC"]
            temp_c   = r["_grid_temp"]   # always °C internally
            ph       = r["_grid_pH"]
            ionic_s  = r.get("ionic_strength", 0.0)

            # Build concentrated water params for this grid point
            conc_params: Dict[str, Any] = {}
            for key, val in base_water_parameters.items():
                if isinstance(val, dict):
                    raw_val = val.get("value", 0)
                    unit    = val.get("unit", "mg/L")
                else:
                    raw_val = val
                    unit    = "mg/L"
                try:
                    numeric = float(raw_val)
                except (TypeError, ValueError):
                    numeric = 0.0
                # pH and Temperature don't scale with CoC
                if key.lower() in ("ph", "temperature", "temp"):
                    conc_params[key] = {"value": numeric, "unit": unit}
                else:
                    conc_params[key] = {"value": round(numeric * coc, 4), "unit": unit}

            # Override pH and Temperature with grid values
            conc_params["pH"]          = {"value": ph,     "unit": ""}
            conc_params["Temperature"] = {"value": temp_c, "unit": "C"}

            # ── Deposition Indices ──────────────────────────────────────────
            indices: Dict[str, Any] = {}
            try:
                indices["lsi"]          = await calc_svc.calculate_lsi(conc_params)
            except Exception as e:
                indices["lsi"]          = {"error": str(e)}
            try:
                indices["ryznar"]       = await calc_svc.calculate_ryznar(conc_params)
            except Exception as e:
                indices["ryznar"]       = {"error": str(e)}
            try:
                indices["puckorius"]    = await calc_svc.calculate_puckorius(conc_params)
            except Exception as e:
                indices["puckorius"]    = {"error": str(e)}
            try:
                indices["larson_skold"] = await calc_svc.calculate_larson_skold(conc_params)
            except Exception as e:
                indices["larson_skold"] = {"error": str(e)}
            try:
                indices["stiff_davis"]  = await calc_svc.calculate_stiff_davis(conc_params, ionic_s)
            except Exception as e:
                indices["stiff_davis"]  = {"error": str(e)}
            # CCPP from SI of Calcite (approximation when no equilibrium phases)
            calcite_si = None
            for k, v in r["saturation_indices"].items():
                if k.lower() == "calcite":
                    calcite_si = v.get("SI") if isinstance(v, dict) else float(v)
                    break
            if calcite_si is not None:
                # Approximate CCPP from SI: CCPP ≈ SI × 50 (rough estimate)
                ccpp_approx = round(calcite_si * 50, 2)
                if ccpp_approx > 15:
                    ccpp_interp, ccpp_risk = "Heavy Scale Forming", "High Scale Risk"
                elif ccpp_approx > 0:
                    ccpp_interp, ccpp_risk = "Slight Scale Forming", "Moderate Scale Risk"
                elif ccpp_approx >= -15:
                    ccpp_interp, ccpp_risk = "Slight Dissolution", "Low Corrosion"
                else:
                    ccpp_interp, ccpp_risk = "Corrosive", "Corrosive"
                indices["ccpp"] = {"ccpp_ppm": ccpp_approx, "interpretation": ccpp_interp, "risk": ccpp_risk}
            else:
                indices["ccpp"] = {"ccpp_ppm": None, "interpretation": "N/A", "risk": "N/A"}

            # ── Cooling Tower Water Balance ─────────────────────────────────
            water_balance: Dict[str, Any] = {}
            if recirc_rate_gpm > 0 and hot_temp_f > 0 and cold_temp_f > 0:
                try:
                    wb = await ct_svc.calculate_tower_water_balance(
                        recirculation_rate_gpm=recirc_rate_gpm,
                        hot_water_temp_f=hot_temp_f,
                        cold_water_temp_f=cold_temp_f,
                        wet_bulb_temp_f=wet_bulb_f or (cold_temp_f - 10),
                        coc=coc,
                        drift_percent=drift_pct,
                        evaporation_factor_percent=evap_factor,
                    )
                    water_balance = {
                        "blowdown_rate_gpm":  wb["blowdown"]["blowdown_rate_gpm"],
                        "makeup_rate_gpm":    wb["makeup"]["makeup_rate_gpm"],
                        "evaporation_gpm":    wb["evaporation"]["evaporation_rate_gpm"],
                        "range_f":            wb["range"]["range_f"],
                        "approach_f":         wb["approach"]["approach_f"],
                        "efficiency_pct":     wb["efficiency"]["efficiency_percent"],
                        "heat_load_btu_hr":   wb["heat_load"]["heat_load_btu_hr"],
                        "cooling_tons":       wb["cooling_tons"]["cooling_tons"],
                    }
                except Exception as e:
                    logger.warning(f"Water balance failed for CoC={coc}: {e}")
                    water_balance = {"error": str(e)}
            else:
                water_balance = {"note": "Provide asset_info with recirculationRate, hotWaterTempF, coldWaterTempF"}

            # ── Chemical Feedrate & Cost ────────────────────────────────────
            chemical_data: Dict[str, Any] = {}
            bd_gpm = water_balance.get("blowdown_rate_gpm") if isinstance(water_balance.get("blowdown_rate_gpm"), (int, float)) else None
            if bd_gpm and bd_gpm > 0 and dosage_ppm > 0:
                try:
                    day_result  = await ct_svc.calculate_chemical_required_per_day(dosage_ppm, bd_gpm)
                    lbs_per_day = day_result["chemical_lbs_per_day"]
                    kg_per_day  = round(lbs_per_day * 0.453592, 3)
                    kg_per_year = round(kg_per_day * 350, 1)
                    lbs_per_year = round(lbs_per_day * 350, 1)
                    chemical_data = {
                        "product_name":   product_name,
                        "dosage_ppm":     dosage_ppm,
                        "lbs_per_day":    lbs_per_day,
                        "kg_per_day":     kg_per_day,
                        "lbs_per_year":   lbs_per_year,
                        "kg_per_year":    kg_per_year,
                    }
                    if product_cost_per_lb > 0:
                        cost_result = await ct_svc.calculate_chemical_cost(dosage_ppm, product_cost_per_lb)
                        chemical_data["cost_per_million_lbs_bd"] = cost_result["cost_per_million_lbs_bd"]
                        chemical_data["annual_cost_usd"] = round(lbs_per_year * product_cost_per_lb, 2)
                except Exception as e:
                    logger.warning(f"Chemical feedrate failed: {e}")
                    chemical_data = {"error": str(e)}
            else:
                chemical_data = {"note": "Provide asset_info.recirculationRate and dosage_ppm for feedrate"}

            # ── Corrosion Rates ─────────────────────────────────────────────
            corrosion: Dict[str, Any] = {}
            si_dict_flat = {
                k: (v.get("SI") if isinstance(v, dict) else float(v))
                for k, v in r["saturation_indices"].items()
            }
            do_ppm = max(0, 14.6 - 0.41 * temp_c)  # simple DO estimate

            metals_to_calc = metallurgy if metallurgy else ["mild_steel"]
            for metal in metals_to_calc:
                metal_key = metal.lower().replace(" ", "_").replace("-", "_")
                try:
                    if "mild_steel" in metal_key or "steel" in metal_key:
                        result_cr = await calc_svc.calculate_mild_steel_corrosion(
                            conc_params, si_dict_flat, do_ppm, temp_c
                        )
                        corrosion["mild_steel"] = result_cr
                    elif "copper" in metal_key:
                        result_cr = await calc_svc.calculate_copper_corrosion(
                            conc_params, si_dict_flat, do_ppm, temp_c, ph
                        )
                        corrosion["copper"] = result_cr
                    elif "admiralty" in metal_key or "brass" in metal_key:
                        # Admiralty brass ≈ copper with slight adjustment
                        result_cr = await calc_svc.calculate_copper_corrosion(
                            conc_params, si_dict_flat, do_ppm, temp_c, ph
                        )
                        cr_adj = round(result_cr["cr_mpy"] * 0.85, 2)
                        corrosion["admiralty_brass"] = {**result_cr, "cr_mpy": cr_adj}
                except Exception as e:
                    logger.warning(f"Corrosion calc failed for {metal}: {e}")
                    corrosion[metal_key] = {"error": str(e)}

            # ── Merge into result ───────────────────────────────────────────
            enriched.append({
                **r,
                "indices":       indices,
                "water_balance": water_balance,
                "chemical":      chemical_data,
                "corrosion":     corrosion,
            })

        return enriched

    # ── STEP: build interactive chart data (no image, no S3) ────────────────
    @staticmethod
    def _build_chart_data(
        results: List[Dict[str, Any]],
        salt_id: Optional[str],
        temp_unit: str,
    ) -> Dict[str, Any]:
        """
        Build frontend-ready structured data for interactive 3D bar chart.
        Frontend (React/Plotly/Three.js) renders this directly.

        Each point contains:
          - coc, temperature, ph  → axis values
          - si                    → bar height (selected salt SI)
          - color                 → green / yellow / red
          - all_si                → every mineral SI at this grid point (for hover panel)
          - ionic_strength, charge_balance_error_pct, activity_of_water
        """
        temp_suffix = "°F" if temp_unit.upper() == "F" else "°C"

        def _get_si(si_dict: Dict, target: Optional[str]) -> Optional[float]:
            if not target:
                return None
            if target in si_dict:
                v = si_dict[target]
                return v.get("SI") if isinstance(v, dict) else float(v)
            tl = target.lower()
            for k, v in si_dict.items():
                if k.lower() == tl:
                    return v.get("SI") if isinstance(v, dict) else float(v)
            return None

        points = []
        for r in results:
            temp_display = round(
                (r["_grid_temp"] * 9/5 + 32) if temp_unit.upper() == "F" else r["_grid_temp"], 2
            )
            si_val = _get_si(r["saturation_indices"], salt_id)
            desc   = r.get("description_of_solution") or {}

            # All minerals at this grid point
            all_si = {
                mineral: {
                    "SI":               info.get("SI") if isinstance(info, dict) else float(info),
                    "log_IAP":          info.get("log_IAP") if isinstance(info, dict) else None,
                    "log_K":            info.get("log_K") if isinstance(info, dict) else None,
                    "chemical_formula": info.get("chemical_formula") if isinstance(info, dict) else None,
                }
                for mineral, info in r["saturation_indices"].items()
            }

            points.append({
                # ── Axis values ──
                "coc":         r["_grid_CoC"],
                "temperature": temp_display,
                "ph":          r["_grid_pH"],
                # ── Bar height ──
                "si":          si_val,
                # ── Color coding ──
                "color":       r["color_code"],
                "color_hex":   _COLOUR_HEX.get(r["color_code"], "#BDC3C7"),
                # ── Solution properties ──
                "ionic_strength":            r.get("ionic_strength"),
                "charge_balance_error_pct":  r.get("charge_balance_error_pct"),
                "activity_of_water":         desc.get("activity_of_water"),
                # ── All mineral SI values (for hover/click panel) ──
                "all_si": all_si,
                # ── Enriched calculations (from _enrich_grid_points) ──
                "indices":       r.get("indices", {}),
                "water_balance": r.get("water_balance", {}),
                "chemical":      r.get("chemical", {}),
                "corrosion":     r.get("corrosion", {}),
                # ── Description of solution (full PHREEQC output) ──
                "description_of_solution": desc,
                "distribution_of_species": r.get("distribution_of_species", {}),
            })

        # Unique axis values (for frontend axis tick generation)
        unique_coc  = sorted(set(p["coc"]         for p in points))
        unique_temp = sorted(set(p["temperature"] for p in points))
        unique_ph   = sorted(set(p["ph"]          for p in points))

        color_labels = {
            "green":  "Protected",
            "yellow": "Caution",
            "red":    "Scale Risk",
            "error":  "No Data",
        }

        return {
            "salt_id":    salt_id,
            "temp_unit":  temp_suffix,
            "axes": {
                "x": {"label": "Cycles of Concentration", "values": unique_coc},
                "y": {"label": f"Temperature ({temp_suffix})",  "values": unique_temp},
                "z": {"label": f"Saturation Index ({salt_id or 'SI'})", "unit": "SI"},
            },
            "color_map":    _COLOUR_HEX,
            "color_labels": color_labels,
            "total_points": len(points),
            "points":       points,   # ← frontend builds the 3D chart from this
        }

    # ── STEP: summary counts ─────────────────────────────────────────────────
    @staticmethod
    def _summary(results: List[Dict]) -> Dict[str, int]:
        counts: Dict[str, int] = {"green": 0, "yellow": 0, "red": 0, "error": 0}
        for r in results:
            counts[r.get("color_code", "error")] = counts.get(r.get("color_code", "error"), 0) + 1
        return counts

    # ─────────────────────────────────────────────────────────────────────────
    # PUBLIC: run_analysis
    # ─────────────────────────────────────────────────────────────────────────
    async def run_analysis(self, req: Dict[str, Any]) -> Dict[str, Any]:
        run_id = str(uuid.uuid4())
        logger.info(f"Saturation run started  run_id={run_id}")

        # 1. Map dynamic water params
        raw_water = req.get("base_water_parameters", {})
        mapped    = _map_water_params(raw_water)
        if not mapped:
            raise ValueError("base_water_parameters could not be mapped to any known ions")

        base_ph = float(mapped.get("pH", 7.0))

        # 2. pH adjustment
        mapped = _apply_ph_adjustment(mapped, req.get("adjustment_chemical"))

        # 3. Thresholds from raw_material_chemistry
        thresholds = _parse_thresholds(req.get("raw_material_chemistry"))

        # 4. Build grid
        grid = self._build_grid(
            coc_min=float(req.get("coc_min", 1.0)),
            coc_max=float(req.get("coc_max", 10.0)),
            coc_interval=float(req.get("coc_interval", 1.0)),
            temp_min=float(req.get("temp_min", 25.0)),
            temp_max=float(req.get("temp_max", 60.0)),
            temp_interval=float(req.get("temp_interval", 5.0)),
            temp_unit=req.get("temp_unit", "F"),
            ph_mode=req.get("ph_mode", "natural"),
            fixed_ph=req.get("fixed_ph"),
            base_ph=base_ph,
        )

        # 5. PHREEQC batch + color
        salt_id           = req.get("salt_id")
        salts_of_interest = req.get("salts_of_interest")

        results, db_used = await self._run_and_color(
            mapped_params=mapped,
            grid=grid,
            salt_id=salt_id,
            salts_of_interest=salts_of_interest,
            thresholds=thresholds,
            balance_cation=req.get("balance_cation", "Na"),
            balance_anion=req.get("balance_anion", "Cl"),
        )

        # 6. Resolve effective salt (case-insensitive match)
        temp_unit = req.get("temp_unit", "F")

        effective_salt = salt_id
        if results:
            sample_si = results[0].get("saturation_indices", {})
            available = list(sample_si.keys())
            logger.info(f"PHREEQC returned {len(available)} minerals: {available[:15]}")

            if salt_id:
                found = any(k.lower() == salt_id.lower() for k in available)
                if not found:
                    logger.warning(
                        f"salt_id '{salt_id}' not found in PHREEQC results. "
                        f"Available: {available[:10]}. Falling back to first available."
                    )
                    effective_salt = available[0] if available else None
                else:
                    effective_salt = next(k for k in available if k.lower() == salt_id.lower())
            else:
                effective_salt = available[0] if available else None

        # 7. Enrich grid points with indices, water balance, chemical, corrosion
        logger.info("📊 Enriching grid points with calculations...")
        try:
            results = await self._enrich_grid_points(results, raw_water, req)
        except Exception as e:
            logger.warning(f"Enrichment failed (non-fatal): {e}")

        # 8. Build interactive chart data (no image, no S3)
        chart_data = self._build_chart_data(results, effective_salt, temp_unit)

        # 8. Summary
        summary = self._summary(results)

        # 9. Save to DB
        doc = {
            "run_id":             run_id,
            "salt_id":            effective_salt,
            "salts_of_interest":  salts_of_interest,
            "dosage_ppm":         float(req.get("dosage_ppm", 2.0)),
            "coc_min":            float(req.get("coc_min", 1.0)),
            "coc_max":            float(req.get("coc_max", 10.0)),
            "coc_interval":       float(req.get("coc_interval", 1.0)),
            "temp_min":           float(req.get("temp_min", 25.0)),
            "temp_max":           float(req.get("temp_max", 60.0)),
            "temp_interval":      float(req.get("temp_interval", 5.0)),
            "temp_unit":          temp_unit,
            "ph_mode":            req.get("ph_mode", "natural"),
            "fixed_ph":           req.get("fixed_ph"),
            "adjustment_chemical": req.get("adjustment_chemical"),
            "balance_cation":     req.get("balance_cation", "Na"),
            "balance_anion":      req.get("balance_anion", "Cl"),
            "database_used":      db_used,
            "total_grid_points":  len(results),
            "grid_results":       results,
            "chart_data":         chart_data,
            "summary":            summary,
            "thresholds":         thresholds,
            "base_water_parameters": raw_water,
            "product_blend":      req.get("product_blend"),
            "raw_material_chemistry": req.get("raw_material_chemistry"),
            "asset_info":         req.get("asset_info"),
            "created_at":         datetime.now(timezone.utc).isoformat(),
        }
        await db.db["saturation_runs"].insert_one(doc)
        logger.info(f"Saturation run saved  run_id={run_id}  summary={summary}")

        return {k: v for k, v in doc.items() if k != "_id"}

    # ─────────────────────────────────────────────────────────────────────────
    # PUBLIC: switch_salt  (re-graph without PHREEQC re-run)
    # ─────────────────────────────────────────────────────────────────────────
    async def switch_salt(self, run_id: str, salt_id: str) -> Dict[str, Any]:
        doc = await db.db["saturation_runs"].find_one({"run_id": run_id})
        if not doc:
            raise ValueError(f"Run not found: {run_id}")

        results    = doc["grid_results"]
        temp_unit  = doc.get("temp_unit", "F")
        thresholds = doc.get("thresholds", {"max_si_at_dose": 0.0, "band_lower": 0.0, "band_upper": 0.5})

        if not results:
            raise ValueError(f"No grid results saved for run_id: {run_id}")

        # Find actual mineral name (case-insensitive) from saved results
        sample_si    = results[0].get("saturation_indices", {})
        available    = list(sample_si.keys())
        salt_id_lower = salt_id.lower()

        # Resolve exact key as stored in DB
        resolved_salt = None
        for k in available:
            if k.lower() == salt_id_lower:
                resolved_salt = k
                break

        if resolved_salt is None:
            raise ValueError(
                f"Salt '{salt_id}' not found in saved results. "
                f"Available salts: {available[:20]}"
            )

        # Re-color for resolved salt (case-insensitive safe)
        for r in results:
            si_info = r["saturation_indices"].get(resolved_salt)
            if si_info is not None:
                si_val = si_info.get("SI", si_info) if isinstance(si_info, dict) else float(si_info)
                r["color_code"] = _color_code(
                    float(si_val),
                    thresholds["max_si_at_dose"],
                    thresholds["band_lower"],
                    thresholds["band_upper"],
                )
            else:
                r["color_code"] = "error"

        # Build interactive chart data for new salt
        chart_data = self._build_chart_data(results, resolved_salt, temp_unit)
        summary    = self._summary(results)

        # Update DB
        await db.db["saturation_runs"].update_one(
            {"run_id": run_id},
            {"$set": {
                "active_salt_id": resolved_salt,
                "chart_data":     chart_data,
                "summary":        summary,
            }},
        )

        return {
            "run_id":     run_id,
            "salt_id":    resolved_salt,
            "chart_data": chart_data,
            "summary":    summary,
        }

    # ─────────────────────────────────────────────────────────────────────────
    # PUBLIC: get_available_salts  (PHREEQC mineral list, cached in MongoDB)
    # ─────────────────────────────────────────────────────────────────────────
    async def get_available_salts(self) -> List[Dict[str, str]]:
        # Try cache first
        cached = await db.get_cached_phreeqc_info("default")
        if cached and cached.get("minerals"):
            return cached["minerals"]

        # Run minimal PHREEQC to get mineral list
        salts = await self._fetch_salts_from_phreeqc()

        # Cache result
        await db.cache_phreeqc_database_info("default", {"minerals": salts})
        return salts

    async def _fetch_salts_from_phreeqc(self) -> List[Dict[str, str]]:
        """Run a minimal PHREEQC input and parse all saturation indices returned."""
        minimal_params = {
            "pH": 7.0, "Temperature": 25.0,
            "Ca": 100.0, "Mg": 30.0, "Na": 50.0, "K": 5.0,
            "HCO3": 150.0, "SO4": 50.0, "Cl": 50.0, "SiO2": 20.0,
        }
        try:
            result = await self.phreeqc._run_phreeqc_single(minimal_params, self.phreeqc.phreeqc_dat)
            salts = []
            for item in result.get("saturation_indices", []):
                if isinstance(item, dict):
                    salts.append({
                        "name":            item.get("mineral_name", ""),
                        "chemical_formula": item.get("chemical_formula", ""),
                        "phase":           item.get("phase", ""),
                    })
            logger.info(f"Fetched {len(salts)} salts from PHREEQC")
            return salts
        except Exception as e:
            logger.error(f"Failed to fetch salts from PHREEQC: {e}")
            return []
