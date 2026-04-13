"""Generate example PHREEQC input for client debugging."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

# Build the PQI without needing PHREEQC executable
ION_PROPERTIES = {
    "Ca":   {"mw": 40.08},  "Mg":   {"mw": 24.31},
    "Na":   {"mw": 22.99},  "K":    {"mw": 39.10},
    "Cl":   {"mw": 35.45},  "SO4":  {"mw": 96.06},
    "HCO3": {"mw": 61.02},  "SiO2": {"mw": 60.08},
    "Fe":   {"mw": 55.85},  "Mn":   {"mw": 54.94},
}

ION_MAP = {
    "Ca":   ("Ca",         "Ca"),
    "Mg":   ("Mg",         "Mg"),
    "Na":   ("Na",         "Na"),
    "K":    ("K",          "K"),
    "Cl":   ("Cl",         "Cl"),
    "SO4":  ("S(6)",       "SO4"),
    "HCO3": ("Alkalinity", "HCO3"),
    "SiO2": ("Si",         "SiO2"),
    "Fe":   ("Fe(2)",      "Fe"),
    "Mn":   ("Mn",         "Mn"),
}

def f2c(f): return round((f - 32) * 5 / 9, 2)

def build_pqi(base_params, grid):
    lines = []
    for i, point in enumerate(grid, start=1):
        lines.append(f"SOLUTION {i}  # CoC={point['CoC']}, Temp={point['temp_f']}F/{point['temp']:.1f}C, pH={point['pH']}")
        lines.append(f"    pH    {point['pH']:.2f}")
        lines.append(f"    temp  {point['temp']:.1f}")
        coc = point["CoC"]
        for key, (phreeqc_name, as_name) in ION_MAP.items():
            val = base_params.get(key)
            if val and val > 0:
                mw = ION_PROPERTIES[key]["mw"]
                mmol = (val * coc) / mw
                lines.append(f"    {phreeqc_name:12s} {mmol:.6f}  as {as_name}")
        lines.append("")
    lines += ["SELECTED_OUTPUT", "    -saturation_indices", "    -molalities",
              "    -charge_balance", "    -ionic_strength", "", "END"]
    return "\n".join(lines)

# ── Client's base water (from spreadsheet) ───────────────────────────────────
# Calcium 35 as CaCO3  → Ca mg/L = 35 × (40.08/100.09) = 14.02
# Magnesium 20 as CaCO3 → Mg mg/L = 20 × (24.31/100.09) = 4.86
# M Alkalinity 35 as CaCO3 → HCO3 = 35 mg/L as CaCO3
# Sulfur 20 as SO4
# Chloride 15 as Cl
# Silica 16 as SiO2
# pH 6.5 (base, calculated at each grid point)
base = {
    "Ca":   14.02,
    "Mg":   4.86,
    "HCO3": 35.0,
    "SO4":  20.0,
    "Cl":   15.0,
    "SiO2": 16.0,
}

# ── 10×10 grid: CoC 1-10, Temp 110-150°F ─────────────────────────────────────
coc_vals = list(range(1, 11))
temp_f_vals = [110, 120, 130, 140, 150]

grid = []
for coc in coc_vals:
    for tf in temp_f_vals:
        grid.append({"CoC": coc, "temp": f2c(tf), "temp_f": tf, "pH": 6.5})

print(f"Grid: {len(coc_vals)} CoC × {len(temp_f_vals)} Temp = {len(grid)} points")
print(f"Temp: {temp_f_vals[0]}-{temp_f_vals[-1]}°F = {f2c(temp_f_vals[0])}-{f2c(temp_f_vals[-1])}°C")
print()

pqi = build_pqi(base, grid)

# Show specific solutions
lines = pqi.split("\n")
sol_starts = [i for i, l in enumerate(lines) if l.startswith("SOLUTION ")]

def show_solution(idx, label):
    print(f"\n{'='*60}")
    print(f"  {label}")
    print('='*60)
    end = sol_starts[idx+1] if idx+1 < len(sol_starts) else len(lines)
    print("\n".join(lines[sol_starts[idx]:end]))

show_solution(0,  "SOLUTION 1  — CoC=1,  Temp=110°F (43.3°C)")
show_solution(4,  "SOLUTION 5  — CoC=1,  Temp=150°F (65.6°C)")
show_solution(5,  "SOLUTION 6  — CoC=2,  Temp=110°F (43.3°C)")
show_solution(49, "SOLUTION 50 — CoC=10, Temp=150°F (65.6°C)")

with open("phreeqc_example_10x10.pqi", "w") as f:
    f.write(pqi)
print(f"\n✅ Full input ({len(grid)} solutions) saved to: phreeqc_example_10x10.pqi")
