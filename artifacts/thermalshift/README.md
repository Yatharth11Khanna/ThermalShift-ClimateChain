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

### Minimum additional physics for a defensible thermal model

Do not interpret the current `cooling_effect_c_per_kwh` constant as a calibrated physical parameter. A minimum lumped room-air model would need an effective thermal capacitance `C_eff`, envelope heat-transfer conductance `UA`, timestamped ambient temperature, and measured internal/door heat loads. Cooling should be driven by measured electrical input and an identified refrigeration COP/capacity relationship under ambient and load conditions; these parameters must be estimated from co-timed facility data, not filled with generic values.

Any product-safety claim additionally requires product temperature or a calibrated product thermal-mass/room-coupling state, representative sensor placement, and validated product limits. Defrost, compressor cycling, door events, inventory, and spatial variation can require further states or constraints. This milestone does not add any of those parameters or change the existing simplified equation.

## Cost, emissions, and provenance

Baseline and optimized cost are each calculated as `sum(hourly_kWh * the same supplied hourly tariff)`. Baseline and optimized emissions are each calculated independently as `sum(hourly_kWh * the same supplied hourly grid_kgco2_per_kwh)`.

Because total cooling electricity is held constant, any modeled emissions difference comes only from moving electricity between hours with different supplied grid-intensity values. It is not inferred from lower energy consumption, and it is not a measured or guaranteed real-world emissions reduction. If grid intensity is constant, the fixed-energy model must report equal baseline and optimized emissions.

Both series now require explicit interval starts, an IANA time-zone identifier, units, and source descriptions. The API validates that each series has 24 offset-aware timestamps at consecutive one-hour intervals and that tariff and grid-emissions intervals match in the same order. It rejects naive timestamps, invalid time-zone offsets, gaps, duplicates, and mismatched series instead of aligning by array position alone. Timestamp strings, units, and source descriptions are echoed into each hourly report and covered by the report hash.

Tariff units must use an ISO currency code per kWh (for example `INR/kWh` or `EUR/kWh`). Grid-emissions values must be `kgCO2/kWh`; convert other source units explicitly before upload. No currency or emissions-unit conversion is inferred.

The CSV import remains at `/api/import-csv` and still requires exactly 24 rows. Its columns are `hour`, `tariff_timestamp`, `baseline_kwh`, `tariff_per_kwh`, `grid_emissions_timestamp`, `grid_kgco2_per_kwh`, and `ambient_heat_gain_c`. The two timestamp columns on each row must refer to the same interval. The upload form collects shared time zone and each series' units and source. The `hour` field is a 0–23 row index; actual interval starts are represented by timestamps.

Input labels are:

- `synthetic_demo`: the built-in demonstration series; not facility measurements.
- `user_supplied_unverified`: values submitted directly or in a CSV; source, meter, measurement status, and provenance have not been independently verified.

The provenance label and source descriptions are caller-supplied metadata, not authentication. Results are marked `illustrative_model_estimate`. The application currently has no independently verified measured input, public-dataset ingestion, live grid feed, meter connection, or refrigeration-equipment connection.

## Reproducible benchmark scenarios

The deterministic cases in `backend/benchmarks.py` are synthetic and are regression checks, not field studies. Results below are from the current optimizer using its documented formulas:

| Scenario | Outcome | Baseline → optimized | Interpretation |
| --- | --- | --- | --- |
| Useful flexibility | Feasible; both temperature traces remain within 2–5 °C. | Energy: 7.2 → 7.2 kWh; cost: 86.40 → 40.80 input-currency units (52.78% lower); modeled emissions: 5.40 → 2.88 kg CO₂ (46.67% lower). | The synthetic baseline concentrates all demand in the six most expensive/highest-intensity hours. Optimized values use the same energy budget but lower-priced/lower-intensity hours. Those percentages describe only this constructed input. |
| Little benefit | Feasible; optimized schedule has no cost or emissions advantage. | Energy: 7.2 → 7.2 kWh; cost: 57.60 → 57.60; modeled emissions: 3.60 → 3.60 kg CO₂. | The baseline is already flat, and the tariff and grid-intensity inputs are constant. Rescheduling cannot change either metric. |
| Infeasible capacity | No schedule returned as feasible. | Requested budget: 12 kWh; maximum allowed by the 0.2 kWh/hour cap: 4.8 kWh over 24 hours. | The exact energy-budget equality conflicts with the hourly electrical-input cap. The API reports infeasibility rather than relaxing either constraint. |

The useful-flexibility case deliberately has a strong time-of-use contrast. It does not establish that a real cold store can achieve those changes. The API tests also check a constant-grid-intensity case: with an unchanged total kWh budget, it cannot produce an emissions reduction.

## Public cold-storage dataset candidate

**Temperature and Humidity Time Series of Cold Storage Room Monitoring**, by Elia Henrichs, Florian Stoll, and Christian Krupitzer, Zenodo version DOI [10.5281/zenodo.15130001](https://doi.org/10.5281/zenodo.15130001), published 2025-04-03. The official [record](https://zenodo.org/records/15130001) and [metadata API](https://zenodo.org/api/records/15130001) list **Creative Commons Attribution 4.0 International (CC BY 4.0)**. Attribute the creators and cite the DOI if reusing the material; check the current record and license terms before redistribution.

The record contains `Raw.zip`, `Preprocessed.zip`, nine DHT22 logger files, `overview.csv`, `experiment_actions.csv`, preprocessing and preliminary-analysis notebooks, logger source, and a wiring diagram. The logger labels temperature in °C and relative humidity in % and samples every five seconds. The action log records door openings/closures and product-in/product-out events. The preprocessing notebook identifies SENSOR01 and SENSOR02 as movable sensors and aligns the preprocessed series to a shared interval by inserting missing values.

I downloaded and inspected the public preprocessed archive and overview; no dataset was added to the app. The nine aligned sensor files each cover **2024-09-02 09:35:25 to 2024-09-11 11:24:55** at five-second spacing (156,835 interval slots). These timestamps have no UTC offset or declared time zone. Missing temperature/humidity slots in the aligned files vary substantially by sensor:

| Sensor | Missing slots | Observed temperature range |
| --- | ---: | ---: |
| SENSOR01 | 966 | 5.3–42.2 °C |
| SENSOR02 | 0 | 5.8–38.7 °C |
| SENSOR03 | 72,391 | 4.8–12.3 °C |
| SENSOR04 | 5,667 | 5.6–21.9 °C |
| SENSOR05 | 125,734 | 6.9–13.3 °C |
| SENSOR06 | 0 | 5.1–22.1 °C |
| SENSOR07 | 0 | 6.0–22.8 °C |
| SENSOR08 | 0 | 9.0–22.3 °C |
| SENSOR09 | 124,135 | 5.4–12.7 °C |

The raw `overview.csv` shows that the sensors' original start/end times differ; SENSOR05 and SENSOR09 begin on 2024-09-09, while the other sensors begin on 2024-09-02. The high temperature spread and large missing spans mean channel identity, sensor movement, missingness, and alignment must be reviewed before interpreting room-wide behavior.

**What these observations can support:** descriptive per-sensor temperature/humidity trends, rate-of-change summaries, inter-sensor variation, missingness analysis, and cautious event-window comparisons around logged door/product actions, using only the dataset's own naive wall-clock timestamps. They do not establish calibrated room heat-transfer dynamics or a counterfactual optimized temperature trajectory.

**What they cannot validate:** the dataset contains no refrigeration electricity, compressor state, thermal cooling output, COP/capacity curve, outside ambient-temperature series, or product-core temperature. Therefore it cannot calibrate the optimizer's energy-to-temperature coefficient or prove electricity use, energy shifting, cost, or emissions savings. Its timestamps have no declared time zone, so they must not be joined to the timezone-aware tariff/emissions input contract without authoritative timezone evidence. The dataset is not ingested; do not fill its missing fields with synthetic demo values.

Source details: [Zenodo record and files](https://zenodo.org/records/15130001), [record metadata and license](https://zenodo.org/api/records/15130001), and the associated [ACSOS-C 2025 publication](https://doi.org/10.1109/ACSOS-C66519.2025.00033). Inspected 2026-10-15.

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
