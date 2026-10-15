"""Deterministic synthetic scenarios for model behavior regression tests."""

from main import Scenario, synthetic_series_metadata


def benchmark_scenarios():
    """Return named cases covering useful, negligible, and infeasible flexibility."""
    return [
        {
            "id": "useful-flexibility",
            "description": (
                "Baseline cooling is concentrated in the six most expensive and "
                "carbon-intensive hours; spreading the same energy budget reduces "
                "both modeled cost and emissions under the supplied hourly series."
            ),
            "scenario": Scenario(
                name="Benchmark: useful flexibility (synthetic)",
                input_provenance="synthetic_demo",
                **synthetic_series_metadata("Synthetic useful-flexibility benchmark"),
                baseline_kwh=[0.0] * 18 + [1.2] * 6,
                tariff_per_kwh=[4.0] * 6 + [6.0] * 6 + [7.0] * 6 + [12.0] * 6,
                grid_kgco2_per_kwh=[0.30] * 6 + [0.40] * 6 + [0.50] * 6 + [0.75] * 6,
                ambient_heat_gain_c=[0.08] * 24,
                initial_temp_c=3.0,
                min_temp_c=2.0,
                max_temp_c=5.0,
                cooling_effect_c_per_kwh=0.15,
                max_cooling_kwh_per_hour=1.2,
            ),
        },
        {
            "id": "little-benefit",
            "description": (
                "A flat baseline already matches uniform tariffs and grid intensity, "
                "so rescheduling cannot improve modeled cost or emissions."
            ),
            "scenario": Scenario(
                name="Benchmark: little benefit (synthetic)",
                input_provenance="synthetic_demo",
                **synthetic_series_metadata("Synthetic little-benefit benchmark"),
                baseline_kwh=[0.3] * 24,
                tariff_per_kwh=[8.0] * 24,
                grid_kgco2_per_kwh=[0.5] * 24,
                ambient_heat_gain_c=[0.08] * 24,
                initial_temp_c=3.0,
                min_temp_c=2.0,
                max_temp_c=5.0,
                cooling_effect_c_per_kwh=0.15,
                max_cooling_kwh_per_hour=1.2,
            ),
        },
        {
            "id": "infeasible-capacity",
            "description": (
                "The requested 12 kWh energy budget exceeds the 4.8 kWh total "
                "available under the 0.2 kWh/hour electrical-input cap."
            ),
            "scenario": Scenario(
                name="Benchmark: infeasible capacity (synthetic)",
                input_provenance="synthetic_demo",
                **synthetic_series_metadata("Synthetic infeasible-capacity benchmark"),
                baseline_kwh=[0.5] * 24,
                tariff_per_kwh=[8.0] * 24,
                grid_kgco2_per_kwh=[0.5] * 24,
                ambient_heat_gain_c=[0.08] * 24,
                initial_temp_c=3.0,
                min_temp_c=2.0,
                max_temp_c=5.0,
                cooling_effect_c_per_kwh=0.15,
                max_cooling_kwh_per_hour=0.2,
            ),
        },
    ]
