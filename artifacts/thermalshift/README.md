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

## Climate scenario comparison API

`POST /api/compare-scenarios` accepts the same scenario input as `/api/optimize` and returns three independently evaluated schedules: the submitted baseline, a cost-optimized schedule, and a carbon-aware schedule. This endpoint does not use the legacy cost/carbon weights or peak penalty.

- **Baseline:** evaluates the submitted hourly cooling electricity without changing it. Its energy, cost, emissions, and peak are calculated from the supplied arrays. The baseline is marked infeasible and includes warnings if it violates an hourly cooling cap or modeled temperature bound; it is never relabeled as optimized.
- **Cost-optimized:** minimizes `sum(tariff_per_kwh[h] * cooling_kwh[h])` using the supplied hourly tariff values. Grid emissions are calculated and reported independently, not included in this objective.
- **Carbon-aware:** minimizes `sum(grid_kgco2_per_kwh[h] * cooling_kwh[h])` using the supplied hourly grid-intensity values. Electricity cost is calculated and reported independently, not included in this objective. No emissions factors are invented or inferred.

Both optimized schedules use the same linear temperature-state equations and configured end-of-hour bounds, the same non-negative hourly electrical-input cap, and the exact baseline total-energy equality. The response includes each schedule's feasibility, constraint warnings, hourly electricity and modeled temperature, total energy, total cost, total modeled emissions, and peak hourly cooling electricity. If a solver cannot produce a feasible schedule, that scenario has `feasible: false`, no hourly schedule, and `metrics: null`; the endpoint does not substitute the baseline. The endpoint omits run-specific timestamps so identical inputs produce deterministic comparison content on the same solver/runtime.

These are model estimates only. The fixed-energy model cannot claim kWh savings; modeled emissions differences arise only from rescheduling against the supplied time-varying grid-intensity series. Inputs and model parameters are not independently verified or calibrated, and outputs do not establish measured or guaranteed real-world savings. The existing `/api/optimize` endpoint and its weighted objective remain unchanged for the dashboard's current workflow.

### Dashboard workflow

Open **Climate Scenario Lab** in the dashboard sidebar. It uses the active scenario: the built-in synthetic demo by default, or the most recently imported user-supplied CSV. Select **Run comparison** to submit that scenario to `POST /api/compare-scenarios`. The dashboard presents baseline, cost-optimized, and carbon-optimized metrics, relative cost/emissions changes, feasibility warnings, hourly electricity, and modeled temperature. Infeasible optimized schedules do not appear as successful results or chart lines. A zero-valued baseline is reported as an absolute difference with percentage change unavailable.

Manual acceptance check: run the lab once with the demo and confirm all three cards and both charts appear; inspect that cost and carbon optimization have separate labels and baseline deltas; verify the energy totals match the baseline and that feasibility status is honored. Then import a 24-row CSV and rerun to confirm it uses the imported scenario. For a failure-state check, submit a scenario known to be infeasible (for example, set maximum hourly cooling below the fixed total-energy budget divided by 24) and confirm optimized cards show `Infeasible`, no optimized metric values are displayed, and no optimized chart line is presented. All values remain illustrative model estimates.

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

Tariff units must use a supported active ISO 4217 alpha-3 currency code per kWh (for example `USD/kWh`, `INR/kWh`, or `EUR/kWh`). The backend validates codes against a bundled local allowlist based on the [ISO 4217 currency-code standard](https://www.iso.org/iso-4217-currency-codes.html); it does not perform network lookups. Grid-emissions values must be `kgCO2/kWh`; convert other source units explicitly before upload. No currency or emissions-unit conversion is inferred.

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

Each feasible optimization report is serialized using RFC 8785 JSON Canonicalization Scheme and hashed with SHA-256. The hash covers canonical report fields before the `evidence` object is added; the evidence block is excluded to avoid a self-referential hash. The verifier recomputes the hash and compares it with the reference. The same canonicalization is used before any optional testnet submission.

A match detects whether report content differs from the content represented by a **trusted reference hash**. The hash does not establish who created the report, where or how inputs were measured, whether the inputs are true, whether the thermal model is physically valid, or whether any claimed result occurred in the real world. A testnet transaction does not change those limitations.

## Optional testnet hash anchor

The anchoring implementation targets **Ethereum Sepolia** (chain ID `11155111`). Ethereum’s network documentation recommends Sepolia for application development; Etherscan lists its chain ID and provides the linked public explorer ([Ethereum network guidance](https://ethereum.org/developers/docs/networks/), [Etherscan supported chains](https://docs.etherscan.io/supported-chains), [Sepolia explorer](https://sepolia.etherscan.io/)).

There is no smart contract. The service implementation can create a zero-value transaction from a dedicated Sepolia wallet to itself and place only the 32-byte report hash in transaction calldata. The destination is therefore the signer address. Anyone can inspect the transaction input on the explorer. This is a public timestamped inclusion of a hash, not a signature by the report author, trusted measurement provenance, validation of the optimization, or proof of energy/emissions savings.

**Public writes are disabled.** Both the API proxy and FastAPI backend reject `POST /api/anchor`, even when Sepolia credentials and `THERMALSHIFT_ANCHOR_ENABLED=true` are configured. The prototype has no authenticated caller identity to authorize spending the server-held key, so environment configuration alone cannot safely enable public writes. The status, report-hash lookup, and on-chain verification endpoints remain available.

The backend still validates the canonical report hash before returning the disabled-write response. The underlying service retains idempotent transaction storage and Sepolia verification, including chain-ID, receipt, calldata, and confirmation-depth checks; no public request can invoke its transaction-submission path. Its SQLite anchor index stores report hash, network, sender/destination, transaction hash, confirmation state, and signed raw transaction for exact retry; it never stores the private key or returns the raw transaction. The report JSON stays unchanged: anchoring metadata is stored separately.

The Replit workspace currently has no Sepolia RPC URL or private-key secret configured, and no transaction has been submitted or confirmed. The dashboard reports that state instead of generating a fake transaction.

## Render deployment (free resources)

The recommended deployment uses a Render Static Site for the Vite frontend and
a Render Free Python Web Service for FastAPI. The dashboard's API routes are
implemented by FastAPI; Express is not needed as a public service in this
arrangement. The Vite `/api` proxy is for local development only. In a
production build, `VITE_API_BASE_URL` configures the generated API client to
prepend the FastAPI service URL while retaining each `/api/...` endpoint path.
If it is unset, API calls remain relative and continue to use the development
proxy locally.

Create the FastAPI Web Service first, then use its assigned HTTPS URL as the
`VITE_API_BASE_URL` build-time environment variable on the Static Site. Do not
include a path such as `/api`; a trailing slash is accepted and removed.

| Setting | Frontend: Static Site | Backend: Free Python Web Service |
| --- | --- | --- |
| Repository | This repository | This repository |
| Root directory | Repository root (leave unset) | Repository root (leave unset so Render finds `uv.lock`) |
| Build command | `pnpm install --frozen-lockfile && PORT=5199 BASE_PATH=/ pnpm --filter @workspace/thermalshift run build` | `uv sync --frozen --no-dev` |
| Publish directory / start command | Publish directory: `artifacts/thermalshift/dist/public` | `uv run --frozen --no-sync --directory artifacts/thermalshift/backend uvicorn main:app --host 0.0.0.0 --port $PORT` |
| Environment | `VITE_API_BASE_URL=https://<actual-fastapi-service>.onrender.com` | Render supplies `PORT`; optionally set `THERMALSHIFT_ANCHOR_ENABLED=false` explicitly |
| Health check | Static Sites do not use a Web Service health-check path | HTTP health check: `/api/health` |

`VITE_API_BASE_URL` is embedded during the Static Site build, not read at
browser runtime. Set it to the actual HTTPS URL Render assigns to the deployed
FastAPI service before building or rebuilding the frontend. The build command's
`PORT` and `BASE_PATH` values are needed by the current Vite configuration;
`PORT` here is only for the build configuration, not a running static server.

The Python service uses the root `pyproject.toml` and `uv.lock`; its start
command runs Uvicorn from the FastAPI backend directory, binds to `0.0.0.0`,
and listens on Render's `$PORT`. Its `/api/health` endpoint returns a
successful health response. The normal optimization and report-hash workflow
does not need blockchain credentials. Public anchor writes remain disabled;
do not set signing keys or expect this deployment to submit transactions.

Render Free Web Services spin down after 15 minutes without inbound traffic;
the first request after that can take about a minute while the service starts.
Free Web Services have ephemeral filesystems, so local files such as the
SQLite anchor index are not durable and can be lost on spin-down, restart, or
redeploy. Render's included free instance-hour budget is shared across the
workspace. The Static Site does not use Web Service instance hours, but the
backend does; review the current Render limits before relying on free-tier
availability. A Render deployment has not yet been created or verified.

## Development checks

### Run in GitHub Codespaces

Start each service in its own terminal from the repository root. The Express
API server listens on port `5000` as documented in the workspace operations
guide; the FastAPI backend listens on `8000`. Vite proxies `/api` to Express
without removing the `/api` prefix. Forward/open Vite's port `5199` in
Codespaces.

```sh
# Terminal 1: FastAPI backend
cd artifacts/thermalshift/backend
PYTHONPATH="$PWD" uv run --project /workspaces/ThermalShift-ClimateChain \
  uvicorn main:app --host 0.0.0.0 --port 8000
```

```sh
# Terminal 2: Express API proxy
PORT=5000 THERMALSHIFT_API_URL=http://127.0.0.1:8000 \
  pnpm --filter @workspace/api-server run dev
```

```sh
# Terminal 3: Vite frontend
PORT=5199 BASE_PATH=/ \
  pnpm --filter @workspace/thermalshift run dev
```

Check routing from the Codespaces terminal with:

```sh
curl -fsS http://127.0.0.1:5199/api/health
```

It should return the FastAPI health JSON through Vite and the Express proxy.
CSV uploads accept up to 100,000 bytes; the Express JSON parser is bounded at
256 KiB to accommodate that CSV plus JSON encoding and scenario metadata.

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
