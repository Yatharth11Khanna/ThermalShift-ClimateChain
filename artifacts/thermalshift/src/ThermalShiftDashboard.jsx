import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { Activity, ArrowDownRight, ArrowUpRight, Check, ChevronDown, CircleHelp, Cloud, Download, FileCheck2, Leaf, LockKeyhole, Play, ShieldCheck, Snowflake, Thermometer, Upload, Zap } from 'lucide-react';
import { useGetThermalShiftDemo, useGetThermalShiftHealth, useImportThermalShiftCsv, useOptimizeThermalShift, useVerifyThermalShiftReportHash } from '@workspace/api-client-react';
import './styles.css';
import './csv-import.css';

const fmt = (v, d = 1) => Number(v ?? 0).toLocaleString(undefined, { maximumFractionDigits: d, minimumFractionDigits: d });
const money = (v) => '₹' + Number(v ?? 0).toLocaleString('en-IN', { maximumFractionDigits: 2 });
const errorText = (e, fallback) => e?.response?.data?.detail || e?.message || fallback;

export default function ThermalShiftDashboard() {
  const demo = useGetThermalShiftDemo();
  const health = useGetThermalShiftHealth();
  const importCsv = useImportThermalShiftCsv();
  const optimize = useOptimizeThermalShift();
  const verifyHash = useVerifyThermalShiftReportHash();
  const [uploadedScenario, setUploadedScenario] = useState(null);
  const [csvSource, setCsvSource] = useState(null);
  const scenario = uploadedScenario ?? demo.data;
  const [report, setReport] = useState(null);
  const [view, setView] = useState('overview');
  const [activeHour, setActiveHour] = useState(14);
  const [weights, setWeights] = useState({ cost: 50, carbon: 50 });
  const [error, setError] = useState('');
  const [verify, setVerify] = useState(null);
  const autoRunStarted = useRef(false);

  const chartData = useMemo(() => Array.isArray(report?.hourly) ? report.hourly : [], [report]);
  const serviceAvailable = health.data?.status === 'ok' || health.data?.status === 'healthy';
  const runOptimize = async () => {
    if (!scenario) return;
    setError('');
    setVerify(null);
    setReport(null);
    try {
      const result = await optimize.mutateAsync({ data: { scenario: { ...scenario, cost_weight: weights.cost / 100, carbon_weight: weights.carbon / 100 } } });
      if (!result?.feasible) {
        setError(result?.message || 'The solver did not find a feasible schedule. Review the scenario guardrails and try again.');
        return;
      }
      setReport(result);
      setView('overview');
    } catch (e) {
      setError(errorText(e, 'Optimization request failed. The API may be unavailable.'));
    }
  };
  useEffect(() => {
    if (scenario && !autoRunStarted.current) {
      autoRunStarted.current = true;
      void runOptimize();
    }
  }, [scenario]);
  const importCsvFile = async (event) => {
    const input = event.currentTarget;
    const file = input.files?.[0];
    if (!file) return;
    setError('');
    try {
      if (!file.name.toLowerCase().endsWith('.csv')) {
        throw new Error('Choose a .csv file.');
      }
      if (file.size > 100000) {
        throw new Error('CSV files must be 100 KB or smaller.');
      }
      const imported = await importCsv.mutateAsync({
        data: { csv_text: await file.text(), scenario },
      });
      const scenarioName = file.name.replace(/\.csv$/i, '') || 'Uploaded CSV';
      setCsvSource({
        fileName: file.name,
        scenarioName,
        recordCount: imported.record_count,
      });
      setUploadedScenario({ ...imported.scenario, name: scenarioName });
      setReport(null);
      setVerify(null);
      autoRunStarted.current = false;
      setView('overview');
    } catch (e) {
      setError(errorText(e, 'CSV import failed.'));
    } finally {
      input.value = '';
    }
  };
  const downloadReport = () => {
    if (!report) return;
    const blob = new Blob([JSON.stringify(report, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'thermalshift-evidence-report.json';
    a.click();
    URL.revokeObjectURL(url);
  };
  const verifyReport = async () => {
    if (!report?.evidence?.report_hash) return;
    setVerify(null);
    try {
      const resultReport = Object.fromEntries(Object.entries(report).filter(([key]) => key !== 'evidence'));
      const result = await verifyHash.mutateAsync({ data: { report: resultReport, report_hash: report.evidence.report_hash } });
      setVerify(result);
    } catch (e) {
      setVerify({ valid: false, note: errorText(e, 'Could not contact the verification API.') });
    }
  };

  const metricCards = report ? [
    { label: 'Modelled emissions', value: `${fmt(report.optimized?.emissions_kgco2, 1)} kg`, change: `${fmt(report.change_pct?.emissions_reduction_pct, 1)}%`, key: 'emissions_reduction_pct', icon: Leaf, tone: 'green' },
    { label: 'Modelled energy cost', value: money(report.optimized?.cost), change: `${fmt(report.change_pct?.cost_reduction_pct, 1)}%`, key: 'cost_reduction_pct', icon: Zap, tone: 'blue' },
    { label: 'Energy consumed', value: `${fmt(report.optimized?.energy_kwh, 1)} kWh`, change: `${fmt(report.change_pct?.energy_reduction_pct, 1)}%`, key: 'energy_reduction_pct', icon: Activity, tone: 'violet' },
    { label: 'Peak load proxy', value: `${fmt(report.optimized?.peak_kw_proxy, 2)} kW`, change: `${fmt(report.change_pct?.peak_reduction_pct, 1)}%`, key: 'peak_reduction_pct', icon: Cloud, tone: 'amber' },
  ] : [];
  const pageTitle = view === 'overview' ? 'Make every cooling hour count.' : view === 'schedule' ? 'A smarter cooling schedule.' : 'Evidence you can independently verify.';

  return <div className="app-shell">
    <aside className="sidebar">
      <div className="brand"><div className="brand-mark"><Snowflake size={22}/></div><div><div className="brand-name">thermal<span>shift</span></div><div className="brand-caption">ENERGY INTELLIGENCE</div></div></div>
      <div className="workspace"><div className="workspace-dot"/><div><b>{csvSource?.scenarioName || 'Demo cold store'}</b><small>Facility workspace</small></div><ChevronDown size={15}/></div>
      <div className="nav-label">WORKSPACE</div>
      <button className={`nav-item ${view === 'overview' ? 'active' : ''}`} onClick={() => setView('overview')}><Activity size={17}/> Overview</button>
      <button className={`nav-item ${view === 'schedule' ? 'active' : ''}`} onClick={() => setView('schedule')}><Snowflake size={17}/> Cooling schedule</button>
      <button className={`nav-item ${view === 'evidence' ? 'active' : ''}`} onClick={() => setView('evidence')}><FileCheck2 size={17}/> Evidence &amp; audit</button>
      <div className="sidebar-bottom">
        <div className="status-card"><div className="status-top"><span className="status-pulse"/> SYSTEM STATUS</div><b>{health.isLoading ? 'Checking optimization service' : serviceAvailable ? 'Optimization engine ready' : 'Optimization service unavailable'}</b><small>{health.data?.version ? `Prototype environment · v${health.data.version}` : 'Prototype environment · status from API'}</small></div>
        <div className="profile"><div className="avatar">TS</div><div><b>ThermalShift Lab</b><small>ClimateChain 2026</small></div><CircleHelp size={17}/></div>
      </div>
    </aside>
    <main className="main-content">
      <header className="topbar"><div className="breadcrumbs">Workspace <span>/</span> <b>{view === 'overview' ? 'Overview' : view === 'schedule' ? 'Cooling schedule' : 'Evidence & audit'}</b></div><div className="top-actions"><div className="demo-pill"><span/> {csvSource ? 'USER-SUPPLIED CSV' : 'SIMULATED DATA'}</div><button className="icon-button" title="Help" onClick={() => setError(csvSource ? 'CSV values are user-supplied; source and meter provenance are not independently verified.' : 'Demo inputs are synthetic. No live equipment or meter readings are connected.')}><CircleHelp size={18}/></button><div className="top-avatar">TS</div></div></header>
      <div className="page-wrap">
        <section className="page-heading"><div><div className="eyebrow"><span className="eyebrow-line"/> CARBON-AWARE COLD STORAGE</div><h1>{pageTitle}</h1><p>{view === 'overview' ? 'Shift flexible refrigeration demand toward cleaner, lower-cost hours—without crossing configured temperature limits.' : view === 'schedule' ? 'Compare the current operating profile with a temperature-constrained optimized schedule.' : 'Review the assumptions, results and cryptographic fingerprint behind this simulation.'}</p></div><div className="heading-actions"><label className={`outline-button csv-upload-button ${importCsv.isPending ? 'is-disabled' : ''}`} aria-disabled={importCsv.isPending}><Upload size={15}/>{importCsv.isPending ? 'Validating CSV…' : 'Upload 24-hour CSV'}<input type="file" accept=".csv,text/csv" onChange={importCsvFile} disabled={importCsv.isPending} aria-label="Upload 24-hour scenario CSV"/></label><button className="primary-button" onClick={runOptimize} disabled={!scenario || optimize.isPending}><Play size={16} fill="currentColor"/>{optimize.isPending ? 'Optimizing…' : 'Run optimization'}</button></div></section>
        <div className="csv-import-info">{csvSource ? <span className="csv-import-success" role="status">{csvSource.recordCount} hourly records imported from {csvSource.fileName}. Values are user-supplied; source and meter provenance are not independently verified.</span> : <span>CSV format: hour (0–23), baseline_kwh, tariff_per_kwh, grid_kgco2_per_kwh, ambient_heat_gain_c. Requires exactly 24 records; values must be finite and non-negative.</span>}</div>
        {error && <div className="error-banner" role="alert">{error}<button onClick={() => setError('')} aria-label="Dismiss error">Dismiss</button></div>}
        {demo.isError && <div className="error-banner" role="alert">Could not load the demo scenario. The API may be unavailable. <button onClick={() => demo.refetch()}>Retry</button></div>}
        {health.isError && !demo.isError && <div className="error-banner" role="alert">Optimization service health could not be confirmed. Requests may still be attempted.</div>}
        <div className="notice"><div className="notice-icon"><CircleHelp size={17}/></div><div><b>Research prototype, not live facility control.</b><span>{report?.data_notice || (csvSource ? 'CSV values are user-supplied and have not been independently verified.' : 'Demo inputs are synthetic and are not facility measurements.')} {report?.evaluation_notice || 'Cost uses the supplied hourly tariff; emissions use the supplied hourly grid intensity. Total cooling energy is fixed to the baseline budget, so modeled emissions changes come only from shifting against time-varying input intensity.'} The thermal model is simplified; outputs are estimates, not verified records or guaranteed real-world savings. Validate against facility-specific equipment, product, and food-safety requirements before operational use.</span></div><button onClick={() => setError(csvSource ? 'CSV values are user-supplied; source and meter provenance are not independently verified. No live equipment is connected.' : 'The current demo uses synthetic 24-hour data and an illustrative linear thermal model. No live equipment is connected.')}>Learn more</button></div>
        {view === 'overview' && <>
          <section className="metric-grid">{metricCards.length ? metricCards.map((m) => { const Icon = m.icon; const positive = Number(report?.change_pct?.[m.key]) >= 0; return <div className="metric-card" key={m.label}><div className="metric-head"><span>{m.label}</span><div className={`metric-icon ${m.tone}`}><Icon size={18}/></div></div><div className="metric-value">{m.value}</div><div className="metric-foot"><span className={`change ${positive ? 'positive' : 'negative'}`}>{positive ? <ArrowDownRight size={14}/> : <ArrowUpRight size={14}/>} {m.change}</span><span>vs. baseline</span></div></div>; }) : ['Estimated emissions', 'Energy cost', 'Energy consumed', 'Peak load proxy'].map((label) => <div className="metric-card" key={label}><div className="metric-head"><span>{label}</span></div><div className="metric-value">{demo.isLoading ? 'Loading…' : '—'}</div><div className="metric-foot"><span>Waiting for a feasible optimization result</span></div></div>)}</section>
          <section className="content-grid">
            <div className="panel chart-panel"><div className="panel-heading"><div><h2>Cooling load profile</h2><p>Baseline vs. optimized hourly electricity use</p></div><div className="legend"><span><i className="legend-baseline"/> Baseline</span><span><i className="legend-optimized"/> Optimized</span></div></div><div className="chart-area">{report && chartData.length ? <ResponsiveContainer width="100%" height="100%"><AreaChart data={chartData} margin={{ top: 10, right: 8, left: -15, bottom: 0 }}><defs><linearGradient id="optimizedFill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#2dd4a7" stopOpacity={0.22}/><stop offset="100%" stopColor="#2dd4a7" stopOpacity={0.01}/></linearGradient></defs><CartesianGrid strokeDasharray="3 5" stroke="#243943" vertical={false}/><XAxis dataKey="hour" tickFormatter={(h) => `${String(h).padStart(2, '0')}:00`} tick={{ fill: '#8296a0', fontSize: 10 }} axisLine={false} tickLine={false} interval={3}/><YAxis tick={{ fill: '#8296a0', fontSize: 10 }} axisLine={false} tickLine={false}/><Tooltip contentStyle={{ background: '#102630', border: '1px solid #29414b', borderRadius: 10, color: '#eaf2f4' }} labelFormatter={(h) => `${String(h).padStart(2, '0')}:00`} formatter={(v, n) => [`${Number(v).toFixed(3)} kWh`, n]}/><Area type="monotone" dataKey="baseline_kwh" name="Baseline" stroke="#728994" strokeWidth={2} strokeDasharray="5 4" fill="transparent"/><Area type="monotone" dataKey="optimized_kwh" name="Optimized" stroke="#2dd4a7" strokeWidth={2.5} fill="url(#optimizedFill)"/></AreaChart></ResponsiveContainer> : <div className="empty-chart">{demo.isLoading ? 'Loading demo data…' : optimize.isPending ? 'Solving schedule…' : 'Run optimization to see results'}</div>}</div><div className="chart-footer"><span><i className="tiny-dot green-dot"/> Schedule optimized across 24 hours</span><span>Hourly intervals · Illustrative model</span></div></div>
            <div className="panel temperature-panel"><div className="panel-heading"><div><h2>Temperature guardrails</h2><p>Configured product-temperature limits</p></div><div className="temp-icon"><Thermometer size={19}/></div></div><div className="temp-range"><div><span>MINIMUM</span><b>{scenario?.min_temp_c ?? '—'}°C</b></div><div className="range-track"><div className="range-safe"/><div className="range-marker" style={{ left: '51%' }}/></div><div><span>MAXIMUM</span><b>{scenario?.max_temp_c ?? '—'}°C</b></div></div><div className="temp-readings"><div className="reading"><span>Lowest simulated</span><b>{report ? `${fmt(report.temperature_check?.min_c, 2)}°C` : '—'}</b></div><div className="reading"><span>Highest simulated</span><b>{report ? `${fmt(report.temperature_check?.max_c, 2)}°C` : '—'}</b></div></div><div className={`safety-status ${report?.temperature_check?.within_configured_limits ? 'safe' : 'warning'}`}><ShieldCheck size={17}/><div><b>{report?.temperature_check?.within_configured_limits ? 'Configured limits respected' : 'Check temperature constraints'}</b><small>{report ? 'Based on the simplified model—not a food-safety certification.' : 'Waiting for a feasible optimization result.'}</small></div></div><div className="mini-note">Model assumption: each kWh of cooling reduces simulated temperature by a fixed coefficient.</div><div className="mini-note">Total cooling-energy budget: fixed to the scenario baseline energy. Optimization shifts timing; it does not create an additional energy budget.</div></div>
          </section>
          <section className="bottom-grid"><div className="panel schedule-panel"><div className="panel-heading"><div><h2>Hourly schedule</h2><p>Select an hour to inspect the operating decision</p></div><button className="text-button" onClick={() => setView('schedule')}>Full schedule <ArrowUpRight size={14}/></button></div><div className="hour-strip">{Array.from({ length: 24 }, (_, i) => { const row = chartData.find((item) => item.hour === i); return <button key={i} onClick={() => setActiveHour(i)} className={`hour-cell ${i === activeHour ? 'selected' : ''} ${row && row.optimized_kwh < row.baseline_kwh - .05 ? 'reduced' : row && row.optimized_kwh > row.baseline_kwh + .05 ? 'increased' : ''}`}><span>{String(i).padStart(2, '0')}</span><i/></button>; })}</div><div className="selected-hour"><div><span>SELECTED HOUR</span><b>{String(activeHour).padStart(2, '0')}:00 – {String((activeHour + 1) % 24).padStart(2, '0')}:00</b></div><div><span>BASELINE</span><b>{chartData[activeHour] ? `${fmt(chartData[activeHour].baseline_kwh, 2)} kWh` : '—'}</b></div><div><span>OPTIMIZED</span><b className="mint-text">{chartData[activeHour] ? `${fmt(chartData[activeHour].optimized_kwh, 2)} kWh` : '—'}</b></div></div></div><div className="panel evidence-card"><div className="evidence-symbol"><LockKeyhole size={21}/></div><div className="evidence-copy"><h2>Evidence integrity</h2><p>Each run produces a local SHA-256 report hash. Chain anchoring is deferred until model inputs and results receive independent validation.</p><div className="evidence-state"><span className="status-pulse"/> {report ? 'Local hash generated' : 'Awaiting report'}</div></div><button className="outline-button" onClick={() => setView('evidence')}>Inspect evidence</button></div></section>
        </>}
        {view === 'schedule' && <section className="panel full-panel"><div className="panel-heading"><div><h2>24-hour cooling plan</h2><p>Optimized consumption, tariff, carbon intensity, and temperature state</p></div><button className="outline-button" onClick={downloadReport} disabled={!report}><Download size={15}/> Export report</button></div>{!report ? <div className="empty-chart">{demo.isLoading ? 'Loading scenario…' : 'Run optimization to display schedule results.'}</div> : <div className="table-wrap"><table><thead><tr><th>Hour</th><th>Baseline kWh</th><th>Optimized kWh</th><th>Tariff (₹/kWh)</th><th>Grid intensity (kg CO₂/kWh)</th><th>Simulated temp.</th></tr></thead><tbody>{chartData.map((r) => <tr key={r.hour}><td>{String(r.hour).padStart(2, '0')}:00</td><td>{fmt(r.baseline_kwh, 3)}</td><td className="mint-text">{fmt(r.optimized_kwh, 3)}</td><td>{fmt(r.tariff, 2)}</td><td>{fmt(r.grid_kgco2_per_kwh, 3)}</td><td>{fmt(r.optimized_temp_c, 2)}°C</td></tr>)}</tbody></table></div>}</section>}
        {view === 'evidence' && <section className="evidence-layout"><div className="panel full-panel"><div className="panel-heading"><div><h2>Evidence record</h2><p>Reproducibility and tamper-evidence for this optimization run</p></div><div className="hash-chip"><LockKeyhole size={14}/> SHA-256</div></div><div className="evidence-block"><span>REPORT FINGERPRINT</span><code>{report?.evidence?.report_hash || 'Run optimization to generate a report hash'}</code><button className="outline-button" onClick={() => report?.evidence?.report_hash && navigator.clipboard?.writeText(report.evidence.report_hash)} disabled={!report?.evidence?.report_hash}><Check size={14}/> Copy hash</button></div><div className="integrity-row"><div className="integrity-icon"><ShieldCheck size={20}/></div><div><b>Local integrity fingerprint generated</b><p>SHA-256 covers canonical report fields, excluding the evidence block. A matching hash detects changes only against a trusted reference; it does not authenticate inputs or validate the model.</p></div></div><div className="chain-placeholder"><div className="chain-icon"><LockKeyhole size={20}/></div><div><b>Blockchain anchoring · Deferred</b><p>No blockchain or public testnet is connected, and no transaction has been submitted. Consider anchoring only after independent validation of the model, inputs, and evaluation.</p></div><span className="planned-tag">NOT CONNECTED</span></div><div className="evidence-actions"><button className="primary-button" onClick={downloadReport} disabled={!report}><Download size={16}/> Download evidence JSON</button><button className="outline-button" onClick={verifyReport} disabled={!report?.evidence?.report_hash || verifyHash.isPending}><ShieldCheck size={16}/>{verifyHash.isPending ? 'Verifying…' : 'Verify report integrity'}</button></div>{verify && <div className={`verify-result ${verify.valid ? 'valid' : 'invalid'}`}><b>{verify.valid ? 'Integrity check passed' : 'Integrity check failed'}</b><p>{verify.note || 'The supplied report fingerprint was compared with a freshly calculated hash.'}</p></div>}<p className="model-disclaimer">This prototype is for research and demonstration. It is not a validated refrigeration controller, food-safety certification, financial settlement system, or proof of independently measured carbon savings.</p></div></section>}
        <footer><div><Snowflake size={15}/> <b>THERMALSHIFT</b><span>Built for IEEE ClimateChain 2026</span></div><span>Prototype v0.1.0 <i/> {csvSource ? 'User-supplied CSV · unverified source' : 'Synthetic demo data'}</span></footer>
      </div>
    </main>
  </div>;
}
