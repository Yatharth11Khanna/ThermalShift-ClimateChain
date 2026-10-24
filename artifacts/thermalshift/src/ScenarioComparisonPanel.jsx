import { useMemo, useState } from 'react';
import { Activity, Play, Thermometer } from 'lucide-react';
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { useCompareThermalShiftScenarios } from '@workspace/api-client-react';
import './scenario-comparison.css';

const scenarioDefinitions = [
  { key: 'baseline', label: 'Baseline', description: 'Submitted hourly cooling profile', color: '#93a8b0' },
  { key: 'cost_optimized', label: 'Cost-optimized', description: 'Minimizes supplied hourly electricity cost', color: '#63b3ed' },
  { key: 'carbon_aware', label: 'Carbon-optimized', description: 'Minimizes supplied hourly grid emissions', color: '#4bd6ad' },
];

const formatNumber = (value, digits = 2) => {
  const number = Number(value);
  return Number.isFinite(number)
    ? number.toLocaleString(undefined, { maximumFractionDigits: digits, minimumFractionDigits: digits })
    : '—';
};

const formatRequestError = (error) => {
  const detail = error?.response?.data?.detail;
  if (Array.isArray(detail)) return detail.map((item) => item?.msg || String(item)).join('; ');
  return (typeof detail === 'string' && detail) || error?.message || 'The comparison request failed.';
};

const scenarioIsFeasible = (result) => result?.feasible === true && Boolean(result?.metrics);

function relativeChange(value, baseline, unit) {
  if (!Number.isFinite(Number(value)) || !Number.isFinite(Number(baseline))) return 'Change unavailable';
  const delta = Number(value) - Number(baseline);
  if (Math.abs(Number(baseline)) < 1e-9) {
    if (Math.abs(delta) < 1e-9) return 'No change from zero baseline';
    return `${delta > 0 ? '+' : '-'}${formatNumber(Math.abs(delta))} ${unit}; percentage unavailable for zero baseline`;
  }
  if (Math.abs(delta) < 1e-9) return 'No change from baseline';
  const direction = delta < 0 ? 'lower' : 'higher';
  const percent = Math.abs(delta / Math.abs(Number(baseline)) * 100);
  return `${formatNumber(Math.abs(delta))} ${unit} ${direction} (${formatNumber(percent, 1)}%)`;
}

function hourlyValue(result, hour, field, allowInfeasible = false) {
  if (!Array.isArray(result?.hourly) || (!allowInfeasible && !scenarioIsFeasible(result))) return null;
  const row = result.hourly.find((item) => item.hour === hour);
  const value = Number(row?.[field]);
  return Number.isFinite(value) ? value : null;
}

function ComparisonChart({ title, subtitle, data, valueUnit, valueKey, min, max, icon: Icon, visibleScenarios, baselineInfeasible }) {
  const chartKeys = scenarioDefinitions.map((definition) => (
    valueKey === 'cooling_kwh' ? `${definition.key}Cooling` : `${definition.key}Temperature`
  ));
  const hasValues = data.some((row) => chartKeys.some((key) => Number.isFinite(row[key])));
  return (
    <section className="panel comparison-chart-panel">
      <div className="comparison-chart-heading">
        <div className="comparison-chart-icon"><Icon size={17} /></div>
        <div><h3>{title}</h3><p>{subtitle}</p></div>
      </div>
      {hasValues ? (
        <div className="comparison-chart">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={data} margin={{ top: 12, right: 10, left: -12, bottom: 2 }}>
              <CartesianGrid strokeDasharray="3 5" stroke="#243943" vertical={false} />
              <XAxis dataKey="hour" tickFormatter={(hour) => `${String(hour).padStart(2, '0')}:00`} tick={{ fill: '#8296a0', fontSize: 10 }} axisLine={false} tickLine={false} interval={3} />
              <YAxis tick={{ fill: '#8296a0', fontSize: 10 }} axisLine={false} tickLine={false} unit={valueUnit} />
              <Tooltip
                contentStyle={{ background: '#102630', border: '1px solid #29414b', borderRadius: 8, color: '#eaf2f4' }}
                labelFormatter={(hour) => `Interval ${String(Number(hour) + 1).padStart(2, '0')}`}
                formatter={(value, name) => [value !== null && value !== undefined && Number.isFinite(Number(value)) ? `${formatNumber(value, 3)} ${valueUnit}` : 'No feasible schedule', name]}
              />
              <Legend wrapperStyle={{ color: '#a8bbc1', fontSize: 11 }} />
              {title === 'Modeled temperature' && Number.isFinite(Number(min)) && (
                <ReferenceLine y={Number(min)} stroke="#d69c5b" strokeDasharray="4 4" label={{ value: 'Min', fill: '#d69c5b', fontSize: 10 }} />
              )}
              {title === 'Modeled temperature' && Number.isFinite(Number(max)) && (
                <ReferenceLine y={Number(max)} stroke="#d69c5b" strokeDasharray="4 4" label={{ value: 'Max', fill: '#d69c5b', fontSize: 10 }} />
              )}
              {scenarioDefinitions.filter((definition) => visibleScenarios[definition.key]).map((definition) => (
                <Line
                  key={definition.key}
                  type="monotone"
                  dataKey={valueKey === 'cooling_kwh' ? `${definition.key}Cooling` : `${definition.key}Temperature`}
                  name={definition.key === 'baseline' && baselineInfeasible ? 'Baseline (infeasible)' : definition.label}
                  stroke={definition.color}
                  strokeWidth={definition.key === 'baseline' ? 1.8 : 2.2}
                  strokeDasharray={definition.key === 'baseline' ? '5 4' : undefined}
                  dot={false}
                  connectNulls={false}
                  isAnimationActive={false}
                />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </div>
      ) : (
        <div className="comparison-chart-empty">No hourly results are available for this comparison.</div>
      )}
    </section>
  );
}

function ScenarioResultCard({ definition, result, baselineResult }) {
  const feasible = scenarioIsFeasible(result);
  const hasResult = result?.feasible === true || result?.feasible === false;
  const costUnit = result?.metrics?.electricity_cost_unit || baselineResult?.metrics?.electricity_cost_unit || 'currency units';
  const warnings = Array.isArray(result?.warnings) ? result.warnings : [];
  const metrics = feasible ? result.metrics : null;
  const costChange = definition.key === 'baseline'
    ? 'Reference schedule'
    : relativeChange(metrics?.electricity_cost, baselineResult?.metrics?.electricity_cost, costUnit);
  const emissionsChange = definition.key === 'baseline'
    ? 'Reference schedule'
    : relativeChange(metrics?.modeled_emissions_kgco2, baselineResult?.metrics?.modeled_emissions_kgco2, 'kg CO2');

  return (
    <article className={`comparison-result-card ${feasible ? 'is-feasible' : hasResult ? 'is-infeasible' : 'is-missing'}`}>
      <div className="comparison-result-heading">
        <span className="comparison-result-swatch" style={{ backgroundColor: definition.color }} />
        <div><h3>{definition.label}</h3><p>{definition.description}</p></div>
      </div>
      <div className={`comparison-feasibility ${feasible ? 'feasibility-good' : hasResult ? 'feasibility-bad' : 'feasibility-unknown'}`} role="status">
        <span />{feasible ? 'Feasible under configured model constraints' : hasResult ? 'Infeasible' : 'No result'}
      </div>
      {metrics ? (
        <dl className="comparison-metrics">
          <div><dt>Total cooling energy</dt><dd>{formatNumber(metrics.energy_kwh)} kWh</dd></div>
          <div><dt>Electricity cost</dt><dd>{formatNumber(metrics.electricity_cost)} {costUnit}</dd></div>
          <div><dt>Modeled CO2 emissions</dt><dd>{formatNumber(metrics.modeled_emissions_kgco2)} kg</dd></div>
          <div><dt>Peak hourly cooling</dt><dd>{formatNumber(metrics.peak_hourly_cooling_kwh)} kWh</dd></div>
        </dl>
      ) : (
        <p className="comparison-no-metrics">Metrics are withheld because no feasible schedule was returned.</p>
      )}
      {definition.key !== 'baseline' && (
        <div className="comparison-deltas">
          <div><span>Cost vs baseline</span><b>{costChange}</b></div>
          <div><span>Modeled CO2 vs baseline</span><b>{emissionsChange}</b></div>
        </div>
      )}
      {warnings.length > 0 && (
        <ul className="comparison-warnings">
          {warnings.map((warning, index) => <li key={`${definition.key}-${index}`}>{warning}</li>)}
        </ul>
      )}
      {!hasResult && <p className="comparison-no-metrics">No scenario output was returned.</p>}
    </article>
  );
}

export default function ScenarioComparisonPanel({ scenario, scenarioLoading = false }) {
  const comparisonMutation = useCompareThermalShiftScenarios();
  const [requestState, setRequestState] = useState(null);
  const currentRequest = requestState?.scenario === scenario ? requestState : null;
  const comparison = currentRequest?.result ?? null;
  const error = currentRequest?.error ?? '';
  const results = comparison?.scenarios ?? {};
  const baselineResult = results.baseline;
  const visibleScenarios = {
    baseline: Array.isArray(baselineResult?.hourly) && baselineResult.hourly.length > 0,
    cost_optimized: scenarioIsFeasible(results.cost_optimized),
    carbon_aware: scenarioIsFeasible(results.carbon_aware),
  };

  const chartData = useMemo(() => Array.from({ length: 24 }, (_, hour) => {
    const baseline = results.baseline;
    const cost = results.cost_optimized;
    const carbon = results.carbon_aware;
    return {
      hour,
      baselineCooling: hourlyValue(baseline, hour, 'cooling_kwh', true),
      cost_optimizedCooling: hourlyValue(cost, hour, 'cooling_kwh'),
      carbon_awareCooling: hourlyValue(carbon, hour, 'cooling_kwh'),
      baselineTemperature: hourlyValue(baseline, hour, 'modeled_temperature_c', true),
      cost_optimizedTemperature: hourlyValue(cost, hour, 'modeled_temperature_c'),
      carbon_awareTemperature: hourlyValue(carbon, hour, 'modeled_temperature_c'),
    };
  }), [results]);

  const runComparison = async () => {
    if (!scenario) return;
    setRequestState({ scenario, result: null, error: '' });
    try {
      const result = await comparisonMutation.mutateAsync({ data: { scenario } });
      if (!result?.scenarios || typeof result.scenarios !== 'object') {
        throw new Error('The API response did not contain scenario results.');
      }
      setRequestState({ scenario, result, error: '' });
    } catch (requestError) {
      setRequestState({ scenario, result: null, error: formatRequestError(requestError) });
    }
  };

  return (
    <section className="scenario-lab" aria-labelledby="scenario-lab-title">
      <div className="panel scenario-lab-toolbar">
        <div>
          <div className="scenario-lab-kicker">CLIMATE SCENARIO LAB</div>
          <h2 id="scenario-lab-title">Three schedules, one input series</h2>
          <p>Cost optimization minimizes the supplied tariff-weighted electricity cost. Carbon optimization independently minimizes the supplied grid-intensity-weighted emissions.</p>
          <small>{scenario?.name || (scenario ? 'Current scenario' : 'Waiting for scenario data')} · Total cooling electricity is fixed to the baseline budget.</small>
        </div>
        <button className="primary-button comparison-run-button" onClick={runComparison} disabled={!scenario || comparisonMutation.isPending}>
          <Play size={15} fill="currentColor" />
          {comparisonMutation.isPending ? 'Comparing…' : 'Run comparison'}
        </button>
      </div>

      {!scenario && <div className="comparison-state" role="status">{scenarioLoading ? 'Loading demo scenario…' : 'Load the demo or import a CSV to compare schedules.'}</div>}
      {error && <div className="comparison-error" role="alert">{error}</div>}
      {comparisonMutation.isPending && !comparison && <div className="comparison-state" role="status">Solving cost and carbon schedules with the same configured constraints…</div>}

      {comparison && (
        <>
          <div className="comparison-model-note">
            <b>Illustrative model estimates, not measured savings.</b>
            <span>{comparison.model_notice || 'Schedules and metrics are estimates from the supplied inputs and simplified thermal model.'} No real-world energy or emissions reduction is asserted.</span>
          </div>
          <div className="comparison-results-grid">
            {scenarioDefinitions.map((definition) => (
              <ScenarioResultCard
                key={definition.key}
                definition={definition}
                result={results[definition.key]}
                baselineResult={baselineResult}
              />
            ))}
          </div>
          <div className="comparison-charts-grid">
            <ComparisonChart
              title="Cooling electricity"
              subtitle="Hourly schedule in kWh; optimized lines appear only for feasible results"
              data={chartData}
              valueUnit=" kWh"
              valueKey="cooling_kwh"
              icon={Activity}
              visibleScenarios={visibleScenarios}
              baselineInfeasible={baselineResult?.feasible === false}
            />
            <ComparisonChart
              title="Modeled temperature"
              subtitle="Aggregate end-of-hour state; not product temperature"
              data={chartData}
              valueUnit=" °C"
              valueKey="modeled_temperature_c"
              min={comparison.constraints?.min_temp_c}
              max={comparison.constraints?.max_temp_c}
              icon={Thermometer}
              visibleScenarios={visibleScenarios}
              baselineInfeasible={baselineResult?.feasible === false}
            />
          </div>
          <p className="comparison-provenance-note">
            Cost uses the supplied tariff array; modeled CO2 uses the supplied grid-intensity array. Each is reported separately, and neither is converted into measured or guaranteed real-world impact.
          </p>
        </>
      )}
    </section>
  );
}
