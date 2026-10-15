import React from 'react';

function SeriesDetails({ title, source, unit }) {
  return (
    <div className="series-metadata-card">
      <b>{title}</b>
      <span className="series-metadata-label">Source description</span>
      <span className="series-metadata-value">{source || 'No source description available'}</span>
      <span className="series-metadata-label">Unit</span>
      <span className="series-metadata-value">{unit || '—'}</span>
    </div>
  );
}

export default function TimeSeriesMetadataPanel({ metadata }) {
  if (!metadata) {
    return (
      <section className="series-metadata-panel">
        <h3>Input time-series provenance</h3>
        <p>Run a feasible schedule to view interval and source metadata.</p>
      </section>
    );
  }

  return (
    <section className="series-metadata-panel" aria-label="Input time-series provenance">
      <div className="series-metadata-heading">
        <div>
          <h3>Aligned hourly input series</h3>
          <p>
            {metadata.interval_count} consecutive one-hour intervals · {metadata.timezone}
          </p>
        </div>
      </div>
      <div className="series-metadata-period">
        <span>First interval start <b>{metadata.first_interval_start}</b></span>
        <span>Last interval start <b>{metadata.last_interval_start}</b></span>
      </div>
      <div className="series-metadata-grid">
        <SeriesDetails
          title="Electricity tariff"
          source={metadata.tariff_source}
          unit={metadata.tariff_unit}
        />
        <SeriesDetails
          title="Grid emissions factor"
          source={metadata.grid_emissions_source}
          unit={metadata.grid_emissions_unit}
        />
      </div>
      <p className="series-metadata-notice">{metadata.source_metadata_notice}</p>
    </section>
  );
}
