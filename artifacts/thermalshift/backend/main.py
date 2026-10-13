import csv
import io
import math
from datetime import datetime, timezone
from hashlib import sha256
from typing import List, Literal, Optional
import numpy as np
import rfc8785
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from scipy.optimize import linprog

app = FastAPI(title="ThermalShift API", version="0.1.0", description="Carbon-aware cold-storage scheduling prototype")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

HOURS = list(range(24))

class Scenario(BaseModel):
    name: str = "Demo cold store"
    input_provenance: Literal["synthetic_demo", "user_supplied_unverified"] = "user_supplied_unverified"
    baseline_kwh: List[float] = Field(min_length=24, max_length=24)
    tariff_per_kwh: List[float] = Field(min_length=24, max_length=24)
    grid_kgco2_per_kwh: List[float] = Field(min_length=24, max_length=24)
    ambient_heat_gain_c: List[float] = Field(min_length=24, max_length=24)
    initial_temp_c: float = 3.0
    min_temp_c: float = 1.0
    max_temp_c: float = 5.0
    cooling_effect_c_per_kwh: float = 0.2
    max_cooling_kwh_per_hour: float = 1.6
    cost_weight: float = 0.5
    carbon_weight: float = 0.5

class OptimizeRequest(BaseModel):
    scenario: Scenario

class CsvImportRequest(BaseModel):
    csv_text: str = Field(min_length=1, max_length=100000)
    scenario: Optional[Scenario] = None


def demo_scenario():
    # Synthetic demonstration data. Not live facility or grid data.
    baseline = [0.78,0.75,0.73,0.72,0.72,0.76,0.82,0.90,0.98,1.02,1.00,0.95,0.92,0.91,0.94,1.00,1.08,1.15,1.18,1.12,1.02,0.94,0.86,0.81]
    tariff = [5.1,4.8,4.6,4.4,4.5,4.9,6.2,7.4,8.1,8.4,7.8,7.1,6.7,6.5,6.9,7.6,8.8,9.4,9.2,8.1,7.2,6.5,5.8,5.3]
    carbon = [0.72,0.70,0.68,0.65,0.62,0.60,0.58,0.56,0.54,0.52,0.50,0.48,0.46,0.44,0.43,0.45,0.49,0.56,0.63,0.68,0.72,0.75,0.76,0.74]
    heat = [0.16,0.15,0.15,0.14,0.14,0.15,0.17,0.19,0.22,0.24,0.25,0.26,0.27,0.27,0.26,0.25,0.24,0.23,0.22,0.21,0.20,0.19,0.18,0.17]
    return Scenario(
        name="Demo cold store · 24 hours",
        input_provenance="synthetic_demo",
        baseline_kwh=baseline,
        tariff_per_kwh=tariff,
        grid_kgco2_per_kwh=carbon,
        ambient_heat_gain_c=heat,
    )

CSV_COLUMNS = {
    "baseline_kwh",
    "tariff_per_kwh",
    "grid_kgco2_per_kwh",
    "ambient_heat_gain_c",
}
CSV_REQUIRED_COLUMNS = {"hour", *CSV_COLUMNS}

def parse_hourly_csv(csv_text: str):
    reader = csv.reader(io.StringIO(csv_text, newline=""), strict=True)
    try:
        raw_headers = next(reader)
    except StopIteration:
        raise HTTPException(422, "CSV is empty or has no header row.")
    except csv.Error as exc:
        raise HTTPException(422, f"CSV could not be parsed: {exc}")

    headers = [header.strip().lstrip("\ufeff") for header in raw_headers]
    if not headers or any(not header for header in headers):
        raise HTTPException(422, "CSV headers must be non-empty.")
    if len(set(headers)) != len(headers):
        raise HTTPException(422, "CSV contains duplicate column headers.")

    missing = sorted(CSV_REQUIRED_COLUMNS - set(headers))
    if missing:
        raise HTTPException(
            422,
            "CSV is missing required columns: " + ", ".join(missing) + ".",
        )

    try:
        rows = [
            (reader.line_num, row)
            for row in reader
            if row and any(value.strip() for value in row)
        ]
    except csv.Error as exc:
        raise HTTPException(422, f"CSV could not be parsed: {exc}")

    if len(rows) != 24:
        raise HTTPException(
            422,
            f"CSV must contain exactly 24 hourly records; found {len(rows)}.",
        )

    header_index = {header: index for index, header in enumerate(headers)}
    values_by_hour = {}
    for line_number, row in rows:
        if len(row) != len(headers):
            raise HTTPException(
                422,
                f"CSV row ending at line {line_number} has {len(row)} fields; expected {len(headers)}.",
            )

        raw_hour = row[header_index["hour"]].strip()
        try:
            numeric_hour = float(raw_hour)
        except ValueError:
            raise HTTPException(422, f"CSV hour at line {line_number} must be an integer from 0 to 23.")
        if not math.isfinite(numeric_hour) or not numeric_hour.is_integer():
            raise HTTPException(422, f"CSV hour at line {line_number} must be an integer from 0 to 23.")
        hour = int(numeric_hour)
        if hour < 0 or hour > 23:
            raise HTTPException(422, f"CSV hour at line {line_number} must be between 0 and 23.")
        if hour in values_by_hour:
            raise HTTPException(422, f"CSV contains duplicate hour {hour}.")

        parsed = {}
        for column in CSV_COLUMNS:
            raw_value = row[header_index[column]].strip()
            try:
                value = float(raw_value)
            except ValueError:
                raise HTTPException(
                    422,
                    f"CSV value for {column} at hour {hour} must be numeric.",
                )
            if not math.isfinite(value):
                raise HTTPException(
                    422,
                    f"CSV value for {column} at hour {hour} must be finite.",
                )
            if value < 0:
                raise HTTPException(
                    422,
                    f"CSV value for {column} at hour {hour} must be non-negative.",
                )
            parsed[column] = value
        values_by_hour[hour] = parsed

    missing_hours = sorted(set(range(24)) - set(values_by_hour))
    if missing_hours:
        raise HTTPException(
            422,
            "CSV must contain each hour from 0 through 23 exactly once; "
            f"missing: {', '.join(map(str, missing_hours))}.",
        )

    series = {
        column: [values_by_hour[hour][column] for hour in range(24)]
        for column in CSV_COLUMNS
    }
    return headers, series

@app.get("/api/health")
def health():
    return {"status": "ok", "service": "ThermalShift API", "version": "0.1.0"}

@app.get("/api/demo")
def demo():
    return demo_scenario().model_dump()

@app.post("/api/import-csv")
def import_csv(payload: CsvImportRequest):
    headers, series = parse_hourly_csv(payload.csv_text)
    base_scenario = payload.scenario or demo_scenario()
    imported_scenario = base_scenario.model_copy(
        update={
            **series,
            "input_provenance": "user_supplied_unverified",
        }
    )
    return {
        "scenario": imported_scenario.model_dump(),
        "record_count": 24,
        "headers": headers,
    }

@app.post("/api/optimize")
def optimize(req: OptimizeRequest):
    s = req.scenario
    n = 24
    arrays = [s.baseline_kwh, s.tariff_per_kwh, s.grid_kgco2_per_kwh, s.ambient_heat_gain_c]
    if any(len(a) != n for a in arrays):
        raise HTTPException(422, "Each hourly series must contain exactly 24 values.")
    scalar_inputs = [
        s.initial_temp_c,
        s.min_temp_c,
        s.max_temp_c,
        s.cooling_effect_c_per_kwh,
        s.max_cooling_kwh_per_hour,
        s.cost_weight,
        s.carbon_weight,
    ]
    if not all(math.isfinite(value) for value in scalar_inputs):
        raise HTTPException(422, "All scenario numeric inputs must be finite.")
    if s.min_temp_c >= s.max_temp_c or s.cooling_effect_c_per_kwh <= 0:
        raise HTTPException(422, "Temperature bounds or cooling coefficient are invalid.")
    if not s.min_temp_c <= s.initial_temp_c <= s.max_temp_c:
        raise HTTPException(422, "Initial temperature must be within the configured safe temperature limits.")
    if s.max_cooling_kwh_per_hour < 0:
        raise HTTPException(422, "Maximum hourly cooling electricity must be non-negative.")
    if s.cost_weight < 0 or s.carbon_weight < 0:
        raise HTTPException(422, "Cost and carbon weights must be non-negative.")
    weight_sum = s.cost_weight + s.carbon_weight
    if not math.isfinite(weight_sum) or weight_sum <= 0:
        raise HTTPException(422, "At least one finite, positive objective weight is required.")

    # Variables x[0:24] = cooling electricity, T[24:48] = temperature at end of each hour.
    # Thermal model: T[h] = T[h-1] + heat_gain[h] - cooling_effect * x[h].
    # It has a carried temperature state, but no calibrated thermal time constant,
    # COP curve, ambient-air state, compressor model, or product-temperature state.
    tariffs = np.asarray(s.tariff_per_kwh, dtype=float)
    carbon = np.asarray(s.grid_kgco2_per_kwh, dtype=float)
    base = np.asarray(s.baseline_kwh, dtype=float)
    heat = np.asarray(s.ambient_heat_gain_c, dtype=float)
    if any(not np.all(np.isfinite(values)) for values in (base, tariffs, carbon, heat)):
        raise HTTPException(422, "Energy, tariff, grid-intensity, and heat-gain inputs must be finite.")
    if np.any(base < 0) or np.any(tariffs < 0) or np.any(carbon < 0) or np.any(heat < 0):
        raise HTTPException(422, "Energy, tariff, grid-intensity, and heat-gain inputs must be non-negative.")
    with np.errstate(over="ignore", invalid="ignore"):
        total_energy = float(np.sum(base))
        total_heat_gain = float(np.sum(heat))
        numeric_scales = [
            total_energy * float(np.max(tariffs)),
            total_energy * float(np.max(carbon)),
            total_energy * s.cooling_effect_c_per_kwh,
            s.cooling_effect_c_per_kwh * s.max_cooling_kwh_per_hour,
            total_heat_gain + abs(s.initial_temp_c),
        ]
    if not all(math.isfinite(value) for value in [total_energy, *numeric_scales]):
        raise HTTPException(422, "Scenario values exceed the supported numeric range.")

    # Normalize the two objective terms so the user weights have a comparable influence.
    cost_term = tariffs / max(float(np.max(tariffs)), 1e-9)
    carbon_term = carbon / max(float(np.max(carbon)), 1e-9)
    total_weight = weight_sum
    objective_x = (s.cost_weight * cost_term + s.carbon_weight * carbon_term) / total_weight
    # Small penalty for excessive hourly peaks; this is a proxy, not a market settlement model.
    c = np.concatenate([objective_x, np.zeros(n), [4.0 / max(s.max_cooling_kwh_per_hour, 1e-9)]])

    A_eq, b_eq = [], []
    for h in range(n):
        row = np.zeros(2*n+1)
        row[n+h] = 1.0
        row[h] = s.cooling_effect_c_per_kwh
        if h == 0:
            rhs = s.initial_temp_c + heat[h]
        else:
            row[n+h-1] = -1.0
            rhs = heat[h]
        A_eq.append(row); b_eq.append(rhs)

    # Preserve the baseline's total cooling-energy budget so the optimizer shifts
    # energy across hours rather than manufacturing savings by using less cooling.
    energy_row = np.zeros(2*n+1)
    energy_row[:n] = 1.0
    A_eq.append(energy_row)
    b_eq.append(total_energy)

    A_ub = []
    b_ub = []
    for h in range(n):
        row = np.zeros(2*n+1)
        row[h] = 1.0
        row[-1] = -1.0
        A_ub.append(row)
        b_ub.append(0.0)

    bounds = [(0.0, s.max_cooling_kwh_per_hour)] * n + [(s.min_temp_c, s.max_temp_c)] * n + [(0.0, s.max_cooling_kwh_per_hour)]
    result = linprog(c, A_ub=np.asarray(A_ub), b_ub=np.asarray(b_ub), A_eq=np.asarray(A_eq), b_eq=np.asarray(b_eq), bounds=bounds, method="highs")
    if not result.success:
        return {"feasible": False, "message": "No schedule satisfies the configured temperature bounds and cooling capacity. Try increasing cooling capacity or widening the safe temperature range.", "solver_message": result.message}

    optimized = np.maximum(result.x[:n], 0)
    temps = result.x[n:2*n]
    # Baseline temperature trace under the same simplified thermal model.
    base_temps = []
    temp = s.initial_temp_c
    for h in range(n):
        temp = temp + heat[h] - s.cooling_effect_c_per_kwh * base[h]
        base_temps.append(temp)
    def metrics(load):
        return {
            "energy_kwh": float(np.sum(load)),
            "cost": float(np.dot(load, tariffs)),
            "emissions_kgco2": float(np.dot(load, carbon)),
            "peak_kw_proxy": float(np.max(load)),
        }
    baseline_metrics = metrics(base)
    optimized_metrics = metrics(optimized)
    provenance_notice = (
        "The built-in demo series are synthetic and are not facility measurements."
        if s.input_provenance == "synthetic_demo"
        else "Inputs are caller-supplied and have not been independently verified; no measured-data provenance is asserted."
    )
    def reduction(old, new):
        return 0.0 if abs(old) < 1e-9 else (old-new)/old*100
    rows = []
    for h in range(n):
        rows.append({"hour": h, "baseline_kwh": round(float(base[h]), 4), "optimized_kwh": round(float(optimized[h]), 4), "tariff": float(tariffs[h]), "grid_kgco2_per_kwh": float(carbon[h]), "baseline_temp_c": round(float(base_temps[h]), 3), "optimized_temp_c": round(float(temps[h]), 3)})
    result_payload = {
        "feasible": True,
        "scenario": s.name,
        "model_output_classification": "illustrative_model_estimate",
        "input_provenance": s.input_provenance,
        "model_notice": "Simplified hourly state model: no calibrated thermal-inertia parameter, COP/efficiency curve, ambient-air state, refrigeration-system capacity model, or product-temperature dynamics. Not an operational controller.",
        "objective_notice": "The objective combines normalized tariff and grid-intensity terms with a peak penalty of 4 / max_cooling_kwh_per_hour; that fixed peak term may materially affect the schedule.",
        "data_notice": provenance_notice,
        "provenance_notice": "The input provenance label is supplied by the caller. This API does not authenticate records or verify that inputs were measured.",
        "evaluation_notice": "Baseline and optimized profiles use the same supplied hourly tariff and grid intensity. Total kWh is fixed to baseline, so modeled emissions differences only reflect time-varying input intensity—not measured or guaranteed real-world savings.",
        "energy_budget_kwh": total_energy,
        "baseline": baseline_metrics,
        "optimized": optimized_metrics,
        "change_pct": {
            "cost_reduction_pct": round(reduction(baseline_metrics["cost"], optimized_metrics["cost"]), 2),
            "emissions_reduction_pct": round(reduction(baseline_metrics["emissions_kgco2"], optimized_metrics["emissions_kgco2"]), 2),
            "energy_reduction_pct": round(reduction(baseline_metrics["energy_kwh"], optimized_metrics["energy_kwh"]), 2),
            "peak_reduction_pct": round(reduction(baseline_metrics["peak_kw_proxy"], optimized_metrics["peak_kw_proxy"]), 2),
        },
        "temperature_check": {
            "min_c": round(float(np.min(temps)), 3), "max_c": round(float(np.max(temps)), 3),
            "baseline_min_c": round(float(np.min(base_temps)), 3), "baseline_max_c": round(float(np.max(base_temps)), 3),
            "within_configured_limits": bool(np.min(temps) >= s.min_temp_c - 1e-6 and np.max(temps) <= s.max_temp_c + 1e-6),
            "baseline_within_configured_limits": bool(np.min(base_temps) >= s.min_temp_c - 1e-6 and np.max(base_temps) <= s.max_temp_c + 1e-6),
        },
        "hourly": rows,
        "weights": {"cost": s.cost_weight, "carbon": s.carbon_weight},
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    canonical = rfc8785.dumps(result_payload)
    result_payload["evidence"] = {
        "algorithm": "SHA-256",
        "report_hash": sha256(canonical).hexdigest(),
        "status": "Hash generated locally; no blockchain transaction has been submitted.",
        "scope": "Detects changes to canonical report content when compared with a trusted reference hash; does not authenticate input provenance, validate measurements or model results, or prove blockchain anchoring.",
    }
    return result_payload

@app.post("/api/verify-hash")
def verify_hash(payload: dict):
    report_hash = payload.get("report_hash", "")
    report = payload.get("report")
    if not isinstance(report, dict) or not report_hash:
        raise HTTPException(422, "Provide report and report_hash.")
    canonical = rfc8785.dumps(report)
    calculated = sha256(canonical).hexdigest()
    return {
        "valid": calculated == report_hash,
        "calculated_hash": calculated,
        "provided_hash": report_hash,
        "note": "This compares the canonical supplied report content with the supplied hash. It does not authenticate input provenance, verify measurements or model validity, or establish a blockchain record.",
    }
