# ThermalShift

ThermalShift is a research prototype for comparing a 24-hour cold-storage cooling schedule with a baseline profile. It is not a refrigeration controller, food-safety certification, energy settlement system, or measurement-verification service.

## Current model

For each hour `h`, the linear planning model chooses cooling electricity `x[h]` and one aggregate end-of-hour temperature state `T[h]`:

```text
T[h] = T[h - 1] + heat_gain[h] - cooling_effect * x[h]
```

It applies these constraints:

```text
min_temp <= T[h] <= max_temp
0 <= x[h] <= max_cooling_kwh_per_hour
sum(x) = sum(baseline_kwh)
```

The fixed-energy equality preserves the baseline's 24-hour electricity budget. It means this model cannot claim total kWh savings. The objective combines normalized hourly tariff and grid-emissions-intensity terms using the configured weights, plus a peak-load proxy penalty with coefficient `4 / max_cooling_kwh_per_hour`. That fixed peak term can materially affect the schedule relative to the normalized cost/emissions terms. `peak_kw_proxy` is the maximum hourly kWh value, interpreted as an average kW proxy for one-hour intervals; it is not a demand-charge or market-settlement calculation.

### What the model represents

- A single aggregate cooling-electricity value and a single scalar temperature state for each one-hour interval.
- User-provided or synthetic per-hour heat-gain increments, tariffs, and grid-emissions-intensity values.
- A fixed conversion coefficient, `cooling_effect_c_per_kwh`, from electricity to temperature change.
- Configured end-of-hour temperature limits, an initial-temperature check, and an hourly electrical-input cap.

The state carries forward from one hour to the next, but this is not a calibrated physical thermal-inertia model: there is no thermal mass, wall/product time constant, or validated heat-transfer parameter. `ambient_heat_gain_c` is a supplied temperature increment per interval, not measured outdoor ambient temperature.

### What is omitted

- Thermal inertia and heat transfer calibrated to a particular room, walls, or stored product.
- A physical coefficient of performance (COP), variable compressor efficiency, refrigerant-cycle behavior, defrost cycles, or compressor on/off logic.
- Ambient-air temperature as a state or causal input; the model instead takes a per-hour heat-gain increment.
- Refrigeration capacity as thermal output. `max_cooling_kwh_per_hour` only caps electrical input in this linear model.
- Product-temperature, spatial-gradient, door-opening, inventory, humidity, and food-safety dynamics.

The configured temperature bounds are scenario inputs, not certification that those bounds are appropriate for a facility or product. Validate all model parameters and any safety limits independently before using the outputs for decisions.

## Cost, emissions, and provenance

Baseline and optimized cost are each calculated as `sum(hourly_kWh * the same supplied hourly tariff)`. Baseline and optimized emissions are each calculated as `sum(hourly_kWh * the same supplied hourly grid_kgco2_per_kwh)`. These quantities are reported separately.

Because total cooling electricity is held constant, any modeled emissions difference comes only from moving electricity between hours with different supplied grid-intensity values. It is not inferred from lower energy consumption, and it is not a measured or guaranteed real-world emissions reduction. If grid intensity is constant, the fixed-energy model must report equal baseline and optimized emissions.

Input labels are:

- `synthetic_demo`: the built-in demonstration series; not facility measurements.
- `user_supplied_unverified`: values submitted directly or in a CSV; source, meter, measurement status, and provenance have not been independently verified.

The provenance label itself is caller-supplied metadata, not authentication. Results are marked `illustrative_model_estimate`. The application currently has no independently verified measured input, public-dataset ingestion, live grid feed, meter connection, or refrigeration-equipment connection.

## Reproducible benchmark scenarios

The deterministic cases in `backend/benchmarks.py` are synthetic and are regression checks, not field studies. Results below are from the current optimizer using its documented formulas:

| Scenario | Outcome | Baseline → optimized | Interpretation |
| --- | --- | --- | --- |
| Useful flexibility | Feasible; both temperature traces remain within 2–5 °C. | Energy: 7.2 → 7.2 kWh; cost: 86.40 → 40.80 input-currency units (52.78% lower); modeled emissions: 5.40 → 2.88 kg CO₂ (46.67% lower). | The synthetic baseline concentrates all demand in the six most expensive/highest-intensity hours. Optimized values use the same energy budget but lower-priced/lower-intensity hours. Those percentages describe only this constructed input. |
| Little benefit | Feasible; optimized schedule has no cost or emissions advantage. | Energy: 7.2 → 7.2 kWh; cost: 57.60 → 57.60; modeled emissions: 3.60 → 3.60 kg CO₂. | The baseline is already flat, and the tariff and grid-intensity inputs are constant. Rescheduling cannot change either metric. |
| Infeasible capacity | No schedule returned as feasible. | Requested budget: 12 kWh; maximum allowed by the 0.2 kWh/hour cap: 4.8 kWh over 24 hours. | The exact energy-budget equality conflicts with the hourly electrical-input cap. The API reports infeasibility rather than relaxing either constraint. |

The useful-flexibility case deliberately has a strong time-of-use contrast. It does not establish that a real cold store can achieve those changes. The API tests also check a constant-grid-intensity case: with an unchanged total kWh budget, it cannot produce an emissions reduction.

## Public cold-storage dataset candidate

**Temperature and Humidity Time Series of Cold Storage Room Monitoring**, Henrichs, Stoll, and Krupitzer, Zenodo record [10.5281/zenodo.15130001](https://doi.org/10.5281/zenodo.15130001), published 2025-04-03. The official [Zenodo record](https://zenodo.org/records/15130001) identifies the dataset license as **Creative Commons Attribution 4.0 International (CC BY 4.0)**. Attribute the creators and link the DOI when reusing it; review the license terms and record for updates before redistribution.

The record describes raw and preprocessed readings from nine DHT22 sensors in one cold-storage room. The CSVs contain date, time, temperature, and humidity; related files include logged door-opening/sensor-movement actions and an overview. The logger source is described as sampling every five seconds. The preprocessing removes repeated headers and aligns series by filling missing values with `NaN`.

**Limitations for ThermalShift:** the dataset does not provide the hourly refrigeration-electricity baseline, tariff, grid-emissions intensity, ambient-temperature series, or model cooling coefficient required by the current optimizer. It is one monitored room and cannot, by itself, validate energy shifting, COP, the simplified temperature equation, or emissions. Its temperatures and actions may support future sensor-data and temperature-dynamics validation after provenance, missing data, units, and time alignment are reviewed. To use it for optimization validation, pair it with suitable measured electrical/refrigeration data and independently sourced hourly tariffs and grid intensity. Do not fill its missing fields with the synthetic demo values or report its readings as integrated in this app; no dataset has been ingested.

Source details: [Zenodo record and files](https://zenodo.org/records/15130001), [record metadata and license](https://zenodo.org/api/records/15130001), and the associated [ACSOS-C 2025 publication](https://doi.org/10.1109/ACSOS-C66519.2025.00033). Checked 2026-10-13.

## Evidence hash: exact scope

Each feasible optimization report is serialized using RFC 8785 JSON Canonicalization Scheme and hashed with SHA-256. The hash covers the canonical report fields generated before the `evidence` object is added; the evidence block is excluded to avoid a self-referential hash. The verifier recomputes that hash from the supplied report object and compares it with the supplied reference hash. The UI removes the evidence block before verification.

A match detects whether the canonical report content differs from the content represented by a **trusted reference hash**. By itself, it does not establish who created the report, where or how its inputs were measured, whether the inputs are true, whether the optimization model is physically valid, or whether any claimed result occurred in the real world. It is not a digital signature, trusted timestamp, independent audit, or blockchain proof. Hashes are generated locally; no testnet is connected and no blockchain transaction has been submitted.

## Development checks

From the repository root:

```sh
cd artifacts/thermalshift/backend
python -m pytest -q
cd ../../..
pnpm --filter @workspace/api-spec run codegen
pnpm --filter @workspace/thermalshift run typecheck
pnpm --filter @workspace/api-server run typecheck
PORT=3000 BASE_PATH=/ pnpm --filter @workspace/thermalshift run build
```
