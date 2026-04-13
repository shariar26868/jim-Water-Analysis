"""
PHREEQC Service - Enhanced
CHANGES:
  - SOLUTION_SPREAD batch support ✅ FIXED
  - Enhanced ion balancing (client formula)
  - Ionic strength check → phreeqc.dat vs pitzer.dat
  - 3D grid calculation support
  - Parse molality, electrical balance, equilibrium phases
"""

import os
import logging
import subprocess
import shutil
import tempfile
import re
import math
from typing import Dict, Any, List, Optional, Tuple

logger = logging.getLogger(__name__)


class PHREEQCService:
    """Enhanced PHREEQC service with batch and ion balancing"""

    # ========================================
    # ION PROPERTIES (MW, charge, meq factor)
    # ========================================
    ION_PROPERTIES = {
        "Ca":  {"mw": 40.08,  "charge": 2},
        "Mg":  {"mw": 24.31,  "charge": 2},
        "Na":  {"mw": 22.99,  "charge": 1},
        "K":   {"mw": 39.10,  "charge": 1},
        "Cl":  {"mw": 35.45,  "charge": -1},
        "SO4": {"mw": 96.06,  "charge": -2},
        "HCO3":{"mw": 61.02,  "charge": -1},
        "CO3": {"mw": 60.01,  "charge": -2},
        "SiO2":{"mw": 60.08,  "charge": 0},
        "Ba":  {"mw": 137.33, "charge": 2},
        "Sr":  {"mw": 87.62,  "charge": 2},
        "Fe":  {"mw": 55.85,  "charge": 2},
        "Al":  {"mw": 26.98,  "charge": 3},
        "F":   {"mw": 19.00,  "charge": -1},
        "PO4": {"mw": 94.97,  "charge": -3},
        "Li":  {"mw": 6.94,   "charge": 1},
        "Zn":  {"mw": 65.38,  "charge": 2},
        "Cu":  {"mw": 63.55,  "charge": 2},
        "Sn":  {"mw": 118.71, "charge": 2},
    }

    # Valid balance ions per client spec
    VALID_CATION_BALANCE = ["Na", "K"]
    VALID_ANION_BALANCE  = ["Cl", "SO4"]

    def __init__(self):
        # Read MODE and select PHREEQC paths. Supported MODE values: "test" (default) or "vps".
        mode = os.getenv("MODE", "test").strip().lower()

        # database filenames (same for both modes)
        default_db = os.getenv("PHREEQC_DEFAULT_DATABASE", "phreeqc.dat")
        pitzer_db = os.getenv("PHREEQC_PITZER_DATABASE", "pitzer.dat")

        # Choose env keys based on MODE
        if mode == "vps":
            exe_path = os.getenv("PHREEQC_EXECUTABLE_PATH_VPS")
            database_dir = os.getenv("PHREEQC_DATABASE_PATH_VPS")
        else:
            exe_path = os.getenv("PHREEQC_EXECUTABLE_PATH")
            database_dir = os.getenv("PHREEQC_DATABASE_PATH")

        # Normalize (strip surrounding quotes/whitespace from .env values)
        if isinstance(exe_path, str):
            exe_path = exe_path.strip().strip('"').strip("'")
        if isinstance(database_dir, str):
            database_dir = database_dir.strip().strip('"').strip("'")

        # Fallback defaults when env vars are not set
        if not exe_path:
            exe_path = (
                os.path.join(os.path.dirname(__file__), "..", "..", "phreeqc", "phreeqc.exe")
                if os.name == "nt"
                else "/usr/local/bin/phreeqc"
            )
        if not database_dir:
            database_dir = os.path.join(os.path.dirname(__file__), "..", "..", "phreeqc", "database")

        self.phreeqc_executable = exe_path
        self.phreeqc_dat = os.path.join(database_dir, default_db)
        self.pitzer_dat = os.path.join(database_dir, pitzer_db)

        # Configurable timeout (seconds) for PHREEQC runs
        self.phreeqc_timeout = int(os.getenv("PHREEQC_TIMEOUT", "30"))

        logger.info(f"PHREEQC mode='{mode}' -> exe='{self.phreeqc_executable}' db_dir='{database_dir}' timeout={self.phreeqc_timeout}s")

        # Run verification at initialization (fail-fast on missing executable / DB)
        self._verified = self._verify_phreeqc()
        if not self._verified:
            raise RuntimeError(f"PHREEQC executable not found or not executable: {self.phreeqc_executable}")

        # Ensure the configured database file exists (fail fast)
        if not os.path.isfile(self.phreeqc_dat):
            raise RuntimeError(
                f"PHREEQC database file not found at startup: {self.phreeqc_dat}. "
                f"If running in Docker set PHREEQC_DB_HOST_PATH to the host DB directory and restart."
            )

    # ========================================
    # VERIFY PHREEQC (Windows-safe, resilient)
    # - Accepts direct path, directory, plain basename, or common locations
    # - Ensures file is executable (os.X_OK)
    # ========================================
    def _verify_phreeqc(self) -> bool:
        try:
            candidate = self.phreeqc_executable
            resolved = None

            # 1) Direct file path that exists and is executable
            if candidate and os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                resolved = candidate

            # 2) If candidate is a directory, try common binary names inside it
            elif candidate and os.path.isdir(candidate):
                for name in ("phreeqc", "phreeqc.exe"):
                    p = os.path.join(candidate, name)
                    if os.path.isfile(p) and os.access(p, os.X_OK):
                        resolved = p
                        break

            # 3) If candidate looks like a basename (no path separator) try shutil.which()
            elif candidate and os.path.basename(candidate) == candidate:
                which_path = shutil.which(candidate)
                if which_path and os.access(which_path, os.X_OK):
                    resolved = which_path

            # 4) Try a few common UNIX locations (useful inside containers)
            if not resolved and os.name != "nt":
                for p in ("/usr/local/bin/phreeqc", "/usr/bin/phreeqc", "/bin/phreeqc"):
                    if os.path.isfile(p) and os.access(p, os.X_OK):
                        resolved = p
                        break

            # 5) Last-resort: if candidate exists but not executable, log that specifically
            if not resolved and candidate and os.path.exists(candidate):
                logger.warning(f"PHREEQC found but not executable: {candidate}")
                return False

            if not resolved:
                logger.warning(f"⚠️ PHREEQC not found: {candidate} (searched PATH and common locations)")
                return False

            # If we resolved to a different path, update the attribute
            if resolved != self.phreeqc_executable:
                logger.info(f"PHREEQC resolved: '{self.phreeqc_executable}' -> '{resolved}'")
                self.phreeqc_executable = resolved

            logger.info(f"✅ PHREEQC found: {self.phreeqc_executable}")

            # NOTE: removed --version check (PHREEQC treats unknown args as input files)
            # Verification only checks existence and executable permission here.
            return True
        except Exception as e:
            logger.error(f"❌ PHREEQC verify failed: {e}")
            return False

    # ========================================
    # IONIC STRENGTH CALCULATION
    # ========================================
    @staticmethod
    def calculate_ionic_strength(water_params: Dict[str, Any]) -> float:
        """
        IS = 0.5 × Σ(Ci × Zi²)   (Ci in mol/L)
        """
        is_value = 0.0
        for ion, props in PHREEQCService.ION_PROPERTIES.items():
            if props["charge"] == 0:
                continue
            mg_l = _get_param_value(water_params, ion)
            if mg_l and mg_l > 0:
                mol_l   = (mg_l / 1000.0) / props["mw"]
                is_value += mol_l * (props["charge"] ** 2)
        return round(0.5 * is_value, 6)

    # ========================================
    # SELECT DATABASE: phreeqc.dat vs pitzer.dat
    # ========================================
    def select_database(
        self,
        water_params: Dict[str, Any],
        ph_range: Tuple[float, float],
        coc_range: Tuple[float, float],
        temp_range: Tuple[float, float]
    ) -> str:
        """
        Client rule:
          Calculate IS at lowest  point (min pH, min CoC, min Temp)
          Calculate IS at highest point (max pH, max CoC, max Temp)
          If BOTH ≤ 0.5  → phreeqc.dat
          If ANY  > 0.5   → pitzer.dat
        """
        # Lowest point
        low_params  = _concentrate_params(water_params, coc_range[0])
        low_params  = _set_ph_temp(low_params, ph_range[0], temp_range[0])
        is_low      = self.calculate_ionic_strength(low_params)

        # Highest point
        high_params = _concentrate_params(water_params, coc_range[1])
        high_params = _set_ph_temp(high_params, ph_range[1], temp_range[1])
        is_high     = self.calculate_ionic_strength(high_params)

        if is_low <= 0.5 and is_high <= 0.5:
            logger.info(f"✅ DB selected: phreeqc.dat  (IS low={is_low}, high={is_high})")
            return self.phreeqc_dat
        else:
            logger.info(f"✅ DB selected: pitzer.dat   (IS low={is_low}, high={is_high})")
            return self.pitzer_dat

    # ========================================
    # ION BALANCING  (client formula, max 2 iter)
    # ========================================
    async def ion_balance(
        self,
        water_params: Dict[str, Any],
        cation_ion: str = "Na",
        anion_ion:  str = "Cl",
        max_iterations: int = 2,
        tolerance_percent: float = 5.0,
        database: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Client algorithm:
          1. Run PHREEQC, read electrical_balance & molality
          2. If error < 0  → adjust cation  (Na or K)
             If error > 0  → adjust anion   (Cl or SO4)
          3. New_value = (electrical_balance / |charge|) + original_value
          4. Iterate max 2 times; if error still > tolerance → raise
        """
        if cation_ion not in self.VALID_CATION_BALANCE:
            raise ValueError(f"Invalid cation balance ion: {cation_ion}. Use {self.VALID_CATION_BALANCE}")
        if anion_ion not in self.VALID_ANION_BALANCE:
            raise ValueError(f"Invalid anion balance ion: {anion_ion}. Use {self.VALID_ANION_BALANCE}")

        db = database or self.phreeqc_dat
        balanced = dict(water_params)
        adjustments = []   # track every adjustment made

        for iteration in range(max_iterations):
            logger.info(f"⚖️  Ion balance iteration {iteration + 1}/{max_iterations}")

            # Run PHREEQC
            result = await self._run_phreeqc_single(balanced, db)

            elec_balance = result.get("electrical_balance", 0.0)
            error_pct    = abs(result.get("charge_balance_error_pct", 0.0))

            logger.info(f"   electrical_balance={elec_balance:.6f}, error={error_pct:.2f}%")

            if error_pct <= tolerance_percent:
                logger.info(f"✅ Ion balance OK at iteration {iteration + 1}")
                balanced["_ion_balanced"]         = True
                balanced["_balance_iterations"]   = iteration + 1
                balanced["_charge_balance_error"] = error_pct
                balanced["_ion_adjustments"]      = adjustments
                return balanced

            # Adjust ion per client formula
            if elec_balance < 0:
                ion       = cation_ion
                charge    = self.ION_PROPERTIES[ion]["charge"]
                current   = _get_param_value(balanced, ion) or 0.0
                new_value = (abs(elec_balance) / abs(charge)) + current
                direction = "increased"
                logger.info(f"   Adjusting cation {ion}: {current:.4f} → {new_value:.4f}")
            else:
                ion       = anion_ion
                charge    = abs(self.ION_PROPERTIES[ion]["charge"])
                current   = _get_param_value(balanced, ion) or 0.0
                new_value = (abs(elec_balance) / charge) + current
                direction = "increased"
                logger.info(f"   Adjusting anion  {ion}: {current:.4f} → {new_value:.4f}")

            adjustments.append({
                "ion":              ion,
                "ion_type":         "cation" if elec_balance < 0 else "anion",
                "original_mmol":    round(current, 6),
                "adjusted_mmol":    round(new_value, 6),
                "delta_mmol":       round(new_value - current, 6),
                "direction":        direction,
                "iteration":        iteration + 1,
                "electrical_balance_before": round(elec_balance, 6),
                "charge_error_pct_before":   round(error_pct, 2),
            })

            balanced = _set_param_value(balanced, ion, new_value)

        # After max iterations still not balanced
        raise ValueError(
            f"Ion balancing failed after {max_iterations} iterations. "
            f"Final error: {error_pct:.2f}% (tolerance: {tolerance_percent}%)"
        )

    # ========================================
    # SINGLE PHREEQC RUN
    # ========================================
    async def _run_phreeqc_single(
        self,
        water_params: Dict[str, Any],
        database: str
    ) -> Dict[str, Any]:
        """
        Write .pqi input → run phreeqc → parse .pqo output
        Returns: saturation_indices, ionic_strength, electrical_balance, molalities
        """
        if not self._verified:
            raise RuntimeError("PHREEQC executable not found")

        pqi_content = self._build_pqi(water_params)
        return await self._execute_phreeqc(pqi_content, database)

    # ========================================
    # SOLUTION_SPREAD BATCH (multiple conditions)
    # ========================================
    async def run_batch_solution_spread(
        self,
        base_water_params: Dict[str, Any],
        grid_points: List[Dict[str, Any]],   # [{"pH":x, "CoC":y, "temp":z}, ...]
        database: str
    ) -> List[Dict[str, Any]]:
        """
        SOLUTION_SPREAD approach:
          - Write ONE .pqi with SOLUTION_SPREAD block
          - Each row = one grid point (pH, CoC, Temp)
          - Single PHREEQC call → all results
        Falls back to sequential if SOLUTION_SPREAD fails.
        """
        if not self._verified:
            raise RuntimeError("PHREEQC executable not found")

        logger.info(f"📦 SOLUTION_SPREAD: {len(grid_points)} points")

        try:
            pqi_content = self._build_solution_spread_pqi(base_water_params, grid_points)
            raw_output  = await self._execute_phreeqc_raw(pqi_content, database)
            results     = self._parse_spread_output(raw_output, grid_points)
            logger.info(f"✅ SOLUTION_SPREAD completed: {len(results)} results")
            return results

        except Exception as e:
            logger.warning(f"⚠️ SOLUTION_SPREAD failed ({e}), falling back to sequential")
            return await self._run_sequential_batch(base_water_params, grid_points, database)

    # ========================================
    # SEQUENTIAL FALLBACK
    # ========================================
    async def _run_sequential_batch(
        self,
        base_water_params: Dict[str, Any],
        grid_points: List[Dict[str, Any]],
        database: str
    ) -> List[Dict[str, Any]]:
        """Fallback: run PHREEQC one-by-one"""
        results = []
        total   = len(grid_points)

        for i, point in enumerate(grid_points):
            try:
                concentrated = _concentrate_params(base_water_params, point["CoC"])
                concentrated = _set_ph_temp(concentrated, point["pH"], point["temp"])
                result       = await self._run_phreeqc_single(concentrated, database)
                result["_grid_pH"]   = point["pH"]
                result["_grid_CoC"]  = point["CoC"]
                result["_grid_temp"] = point["temp"]
                results.append(result)
            except Exception as e:
                logger.error(f"❌ Point {i} failed: {e}")
                results.append({
                    "_grid_pH": point["pH"], "_grid_CoC": point["CoC"],
                    "_grid_temp": point["temp"], "error": str(e)
                })

            if (i + 1) % max(1, total // 10) == 0:
                logger.info(f"   Sequential progress: {(i+1)/total*100:.0f}%")

        return results

    # ========================================
    # BUILD .PQI INPUT (single solution)
    # ========================================
    def _build_pqi(self, water_params: Dict[str, Any]) -> str:
        """Build PHREEQC input file content for single solution"""
        lines = ["SOLUTION 1"]

        # pH
        ph = _get_param_value(water_params, "pH")
        if ph is not None:
            lines.append(f"    pH    {ph}")

        # Temperature
        temp = _get_param_value(water_params, "Temperature")
        if temp is not None:
            lines.append(f"    temp  {temp}")

        # pe
        pe = _get_param_value(water_params, "pe")
        if pe is not None:
            lines.append(f"    pe    {pe}")

        # Ions (mg/L → mmol/kgw)
        ion_map = {
            "Ca":   ("Ca",        "Ca"),
            "Mg":   ("Mg",        "Mg"),
            "Na":   ("Na",        "Na"),
            "K":    ("K",         "K"),
            "Cl":   ("Cl",        "Cl"),
            "SO4":  ("S(6)",      "SO4"),   # PHREEQC requires S(6) not SO4
            "HCO3": ("Alkalinity","HCO3"),
            "SiO2": ("Si",        "SiO2"),
            "Ba":   ("Ba",        "Ba"),
            "Sr":   ("Sr",        "Sr"),
            "Fe":   ("Fe(2)",     "Fe"),
            "Al":   ("Al",        "Al"),
            "F":    ("F",         "F"),
            "PO4":  ("P",         "PO4"),
            "Li":   ("Li",        "Li"),
            "Zn":   ("Zn",        "Zn"),
            "Cu":   ("Cu",        "Cu"),
            "Sn":   ("Sn",        "Sn"),
            "Mn":   ("Mn",        "Mn"),
            "NO3":  ("N(5)",      "NO3"),
        }

        for param_key, (phreeqc_name, as_name) in ion_map.items():
            value = _get_param_value(water_params, param_key)
            if value is not None and value > 0:
                props = self.ION_PROPERTIES.get(param_key)
                if props and props["mw"] > 0:
                    mmol = (value / props["mw"])
                    lines.append(f"    {phreeqc_name:12s} {mmol:.6f}  as {as_name}")

        lines.append("")
        lines.append("SELECTED_OUTPUT")
        lines.append("    -saturation_indices")
        lines.append("    -molalities")
        lines.append("    -charge_balance")
        lines.append("    -ionic_strength")
        lines.append("")
        lines.append("END")

        return "\n".join(lines)

    # ========================================
    # BUILD MULTIPLE SOLUTIONS .PQI - ✅ TRULY FIXED
    # ========================================
    def _build_solution_spread_pqi(
        self,
        base_params: Dict[str, Any],
        grid_points: List[Dict[str, Any]]
    ) -> str:
        """
        Build multiple SOLUTION blocks (one per grid point)
        Each solution has its own pH, temp, AND CoC-adjusted ions
        
        This is more compatible than SOLUTION_SPREAD and handles CoC properly.
        """
        lines = []
        
        ion_map = {
            "Ca":   ("Ca",        "Ca"),
            "Mg":   ("Mg",        "Mg"),
            "Na":   ("Na",        "Na"),
            "K":    ("K",         "K"),
            "Cl":   ("Cl",        "Cl"),
            "SO4":  ("S(6)",      "SO4"),
            "HCO3": ("Alkalinity","HCO3"),
            "SiO2": ("Si",        "SiO2"),
            "Ba":   ("Ba",        "Ba"),
            "Sr":   ("Sr",        "Sr"),
            "Fe":   ("Fe(2)",     "Fe"),
            "Mn":   ("Mn",        "Mn"),
        }

        # Create one SOLUTION block per grid point
        for i, point in enumerate(grid_points, start=1):
            lines.append(f"SOLUTION {i}")
            lines.append(f"    pH    {point['pH']:.2f}")
            lines.append(f"    temp  {point['temp']:.1f}")

            coc = point.get("CoC", 1.0)

            for param_key, (phreeqc_name, as_name) in ion_map.items():
                base_value = _get_param_value(base_params, param_key)
                if base_value is not None and base_value > 0:
                    props = self.ION_PROPERTIES.get(param_key)
                    if props and props["mw"] > 0:
                        concentrated_value = base_value * coc
                        mmol = concentrated_value / props["mw"]
                        lines.append(f"    {phreeqc_name:12s} {mmol:.6f}  as {as_name}")

            lines.append("")
        
        # Single SELECTED_OUTPUT block for all solutions
        lines.append("SELECTED_OUTPUT")
        lines.append("    -saturation_indices")
        lines.append("    -molalities")
        lines.append("    -charge_balance")
        lines.append("    -ionic_strength")
        lines.append("")
        lines.append("END")
        
        return "\n".join(lines)

    # ========================================
    # EXECUTE PHREEQC (subprocess)
    # ========================================
    async def _execute_phreeqc(self, pqi_content: str, database: str) -> Dict[str, Any]:
        """Write .pqi, run phreeqc, parse .pqo"""
        with tempfile.TemporaryDirectory() as tmpdir:
            pqi_path = os.path.join(tmpdir, "input.pqi")
            pqo_path = os.path.join(tmpdir, "output.pqo")

            with open(pqi_path, "w") as f:
                f.write(pqi_content)

            # Defensive: warn if database file is missing (common container misconfigure)
            if not os.path.isfile(database):
                logger.warning(
                    f"PHREEQC database file not found: {database} — check PHREEQC_DATABASE_PATH or file mounts"
                )

            cmd = [self.phreeqc_executable, pqi_path, pqo_path, database]
            logger.debug(f"Running PHREEQC command: {cmd}")

            # Run PHREEQC (use configurable timeout)
            timeout_sec = self.phreeqc_timeout if os.name != "nt" else max(self.phreeqc_timeout, 60)
            try:
                result = subprocess.run(
                    cmd,
                    capture_output=True, text=True,
                    timeout=timeout_sec
                )
            except subprocess.TimeoutExpired as exc:
                out = (exc.output or "")[:2000]
                err = (exc.stderr or "")[:2000]
                logger.error(
                    "PHREEQC timed out", extra={
                        "cmd": cmd, "timeout_s": timeout_sec, "stdout": out, "stderr": err
                    }
                )
                # include helpful debugging info
                snippet = pqi_content[:1500]
                raise RuntimeError(
                    f"PHREEQC timed out after {timeout_sec}s.\ncmd={cmd}\nstdout={out!r}\nstderr={err!r}\ninput_pqi_preview={snippet!r}"
                ) from exc

            if result.returncode != 0:
                logger.error(
                    "PHREEQC process failed",
                    extra={"rc": result.returncode, "stderr": (result.stderr or '')[:2000]}
                )
                raise RuntimeError(f"PHREEQC error (rc={result.returncode}): {result.stderr}")

            # Parse output
            with open(pqo_path, "r") as f:
                output_text = f.read()

            return self._parse_phreeqc_output(output_text)

    async def _execute_phreeqc_raw(self, pqi_content: str, database: str) -> str:
        """Run PHREEQC and return raw output text"""
        with tempfile.TemporaryDirectory() as tmpdir:
            pqi_path = os.path.join(tmpdir, "input.pqi")
            pqo_path = os.path.join(tmpdir, "output.pqo")

            with open(pqi_path, "w") as f:
                f.write(pqi_content)

            try:
                batch_timeout = max(self.phreeqc_timeout * 2, 120) if os.name != "nt" else max(self.phreeqc_timeout * 2, 180)
                result = subprocess.run(
                    [self.phreeqc_executable, pqi_path, pqo_path, database],
                    capture_output=True, text=True,
                    timeout=batch_timeout
                )
            except subprocess.TimeoutExpired as exc:
                out = (exc.output or "")[:2000]
                err = (exc.stderr or "")[:2000]
                logger.error("PHREEQC batch timed out", extra={"timeout_s": batch_timeout, "stdout": out, "stderr": err})
                raise RuntimeError(f"PHREEQC batch timed out after {batch_timeout}s; stderr={err!r}") from exc

            if result.returncode != 0:
                logger.error("PHREEQC batch process failed", extra={"rc": result.returncode, "stderr": (result.stderr or '')[:2000]})
                raise RuntimeError(f"PHREEQC error: {result.stderr}")

            with open(pqo_path, "r") as f:
                return f.read()

    # ========================================
    # PARSE SINGLE OUTPUT
    # ========================================
    def _parse_phreeqc_output(self, output_text: str) -> Dict[str, Any]:
        """
        Parse PHREEQC .pqo output:
          - Saturation Indices
          - Ionic Strength
          - Electrical Balance / Charge Balance Error
          - Molalities
          - Equilibrium Phases (CCPP)
        """
        parsed = {
            "saturation_indices":      [],
            "ionic_strength":          0.0,
            "electrical_balance":      0.0,
            "charge_balance_error_pct":0.0,
            "molalities":              {},
            "equilibrium_phases":      {},
            "database_used":           "unknown"
        }

        lines = output_text.split("\n")

        # --- Saturation Indices ---
        # PHREEQC output format:
        # "------------------------------Saturation indices-------------------------------"
        # "  Phase               SI** log IAP   log K(298 K,   1 atm)"
        # "  Anhydrite        -2.09     -6.37   -4.28  CaSO4"
        in_si_block = False
        for line in lines:
            stripped = line.strip()

            # Header detection — case-insensitive
            if re.search(r"saturation indices", stripped, re.IGNORECASE):
                in_si_block = True
                continue

            if in_si_block:
                # Skip empty lines, dashes, and column header lines
                if not stripped or stripped.startswith("-") or stripped.startswith("Phase") or stripped.startswith("**"):
                    if stripped.startswith("**") or stripped.startswith("End of"):
                        in_si_block = False
                    continue

                # Format: "  Anhydrite        -2.09     -6.37   -4.28  CaSO4"
                parts = stripped.split()
                if len(parts) >= 2:
                    try:
                        mineral  = parts[0]
                        si_val   = float(parts[1])
                        log_iap  = float(parts[2]) if len(parts) > 2 else None
                        log_k    = float(parts[3]) if len(parts) > 3 else None
                        # formula is last token if it contains letters (e.g. CaSO4, CaCO3)
                        formula  = parts[-1] if len(parts) > 4 and re.search(r'[A-Za-z]', parts[-1]) else None
                        phase    = parts[4] if len(parts) > 4 and parts[4] != formula else None

                        parsed["saturation_indices"].append({
                            "mineral_name":     mineral,
                            "si_value":         round(si_val, 4),
                            "log_IAP":          round(log_iap, 4) if log_iap is not None else None,
                            "log_K":            round(log_k, 4)   if log_k   is not None else None,
                            "phase":            phase,
                            "chemical_formula": formula,
                        })
                    except (ValueError, IndexError):
                        pass

        # --- Ionic Strength ---
        for line in lines:
            if "Ionic strength" in line:
                match = re.search(r"([-+]?\d+\.?\d*(?:[eE][-+]?\d+)?)", line.split("=")[-1])
                if match:
                    parsed["ionic_strength"] = float(match.group(1))

        # --- Charge Balance ---
        for line in lines:
            if "Charge balance" in line or "electrical balance" in line.lower():
                match = re.search(r"([-+]?\d+\.?\d*(?:[eE][-+]?\d+)?)", line.split("=")[-1] if "=" in line else line)
                if match:
                    parsed["electrical_balance"] = float(match.group(1))

            if "% error" in line.lower() or "charge balance error" in line.lower():
                match = re.search(r"([-+]?\d+\.?\d*)", line)
                if match:
                    parsed["charge_balance_error_pct"] = float(match.group(1))

        # --- Molalities ---
        in_molality = False
        for line in lines:
            if "Molalities" in line or "Total molality" in line:
                in_molality = True
                continue
            if in_molality:
                match = re.match(r"^\s+(\S+)\s+([-+]?\d+\.?\d*(?:[eE][-+]?\d+)?)", line)
                if match:
                    parsed["molalities"][match.group(1)] = float(match.group(2))
                elif line.strip() == "":
                    in_molality = False

        # --- Equilibrium Phases (for CCPP) ---
        in_eq_phase = False
        for line in lines:
            if "Equilibrium phases" in line or "Phase equilibria" in line:
                in_eq_phase = True
                continue
            if in_eq_phase:
                match = re.match(r"^\s+(\S+)\s+.*\s+([-+]?\d+\.?\d*(?:[eE][-+]?\d+)?)\s*$", line)
                if match:
                    parsed["equilibrium_phases"][match.group(1)] = float(match.group(2))
                elif line.strip() == "":
                    in_eq_phase = False

        # --- Description of Solution ---
        desc: Dict[str, Any] = {}
        for line in lines:
            if "pH" in line and "=" in line and "pe" not in line.lower():
                m = re.search(r"pH\s*=\s*([\d.]+)", line)
                if m:
                    desc["pH"] = float(m.group(1))
            if "Temperature" in line and "=" in line:
                m = re.search(r"Temperature\s*=\s*([\d.]+)", line)
                if m:
                    desc["temperature_C"] = float(m.group(1))
            if "Density" in line and "=" in line:
                m = re.search(r"Density\s*=\s*([\d.eE+\-]+)", line)
                if m:
                    desc["density"] = float(m.group(1))
            if "Activity of water" in line:
                m = re.search(r"Activity of water\s*=\s*([\d.eE+\-]+)", line)
                if m:
                    desc["activity_of_water"] = float(m.group(1))
        if desc:
            parsed["description_of_solution"] = desc

        return parsed

    # ========================================
    # PARSE SOLUTION_SPREAD OUTPUT
    # ========================================
    def _parse_spread_output(
        self,
        output_text: str,
        grid_points: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Parse multi-solution PHREEQC output.
        Each SOLUTION block becomes a separate simulation in PHREEQC output,
        separated by: "----\nReading input data for simulation N.\n----"
        """
        results = []

        # Split on simulation boundaries — this is the reliable separator
        # Pattern: dashes, "Reading input data for simulation N.", dashes
        sim_blocks = re.split(
            r"-{3,}\s*\nReading input data for simulation \d+\.\s*\n-{3,}",
            output_text
        )

        # sim_blocks[0] = database reading preamble (skip)
        # sim_blocks[1] = simulation 1 output
        # sim_blocks[2] = simulation 2 output ... etc
        # Last block may be "End of Run" — filter those out
        solution_blocks = [
            b for b in sim_blocks[1:]
            if b.strip() and "Saturation indices" in b
        ]

        logger.debug(f"Split into {len(solution_blocks)} simulation blocks for {len(grid_points)} grid points")

        for i, block in enumerate(solution_blocks):
            if i >= len(grid_points):
                break
            parsed = self._parse_phreeqc_output(block)
            parsed["_grid_pH"]   = grid_points[i]["pH"]
            parsed["_grid_CoC"]  = grid_points[i]["CoC"]
            parsed["_grid_temp"] = grid_points[i]["temp"]
            results.append(parsed)

        # If still fewer results than grid points, raise to trigger sequential fallback
        if len(results) < len(grid_points):
            logger.warning(
                f"_parse_spread_output: got {len(results)} blocks for {len(grid_points)} points. "
                "Triggering sequential fallback."
            )
            raise ValueError("Spread parse yielded fewer results than grid points — use sequential")

        return results

    # ========================================
    # HIGH-LEVEL: FULL ANALYSIS (single point)
    # ========================================
    async def analyze(
        self,
        water_params: Dict[str, Any],
        calculation_type: str = "standard",
        balance_cation: str = "Na",
        balance_anion:  str = "Cl"
    ) -> Dict[str, Any]:
        """
        Full single-point analysis:
          1. Ion balance
          2. Select database
          3. Run PHREEQC
          4. Return parsed results
        """
        # Select database (single-point: use current values as range)
        ph   = _get_param_value(water_params, "pH") or 7.0
        temp = _get_param_value(water_params, "Temperature") or 25.0
        database = self.select_database(
            water_params,
            ph_range=(ph, ph),
            coc_range=(1.0, 1.0),
            temp_range=(temp, temp)
        )

        # Ion balance
        balanced = await self.ion_balance(
            water_params,
            cation_ion=balance_cation,
            anion_ion=balance_anion,
            database=database
        )

        # Run final analysis with balanced water
        result = await self._run_phreeqc_single(balanced, database)
        result["database_used"] = os.path.basename(database)

        return result


# ========================================
# MODULE-LEVEL HELPERS
# ========================================

def _get_param_value(params: Dict[str, Any], key: str) -> Optional[float]:
    """Extract numeric value from params dict (handles nested {value, unit})"""
    val = params.get(key)
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, dict):
        return float(val.get("value", 0))
    return None


def _set_param_value(params: Dict[str, Any], key: str, value: float) -> Dict[str, Any]:
    """Set a param value (preserves nested structure if present)"""
    out = dict(params)
    existing = out.get(key)
    if isinstance(existing, dict):
        existing["value"] = value
    else:
        out[key] = {"value": value, "unit": "mg/L"}
    return out


def _concentrate_params(params: Dict[str, Any], coc: float) -> Dict[str, Any]:
    """Multiply all ion concentrations by CoC (skip pH, Temperature, pe)"""
    skip = {"pH", "Temperature", "pe", "Eh", "_ion_balanced",
            "_balance_iterations", "_charge_balance_error"}
    out = {}
    for k, v in params.items():
        if k in skip:
            out[k] = v
        elif isinstance(v, dict) and "value" in v:
            out[k] = {**v, "value": v["value"] * coc}
        elif isinstance(v, (int, float)):
            out[k] = v * coc
        else:
            out[k] = v
    return out


def _set_ph_temp(params: Dict[str, Any], ph: float, temp: float) -> Dict[str, Any]:
    """Override pH and Temperature"""
    out = dict(params)
    out["pH"]          = {"value": ph,   "unit": ""}
    out["Temperature"] = {"value": temp, "unit": "°C"}
    return out