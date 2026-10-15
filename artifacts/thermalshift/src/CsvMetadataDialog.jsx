import React, { useState } from 'react';

const emptyMetadata = {
  timezone: '',
  tariff_unit: '',
  tariff_source: '',
  grid_emissions_unit: '',
  grid_emissions_source: '',
};

export default function CsvMetadataDialog({
  fileName,
  busy,
  error,
  onCancel,
  onSubmit,
}) {
  const [metadata, setMetadata] = useState(emptyMetadata);

  const updateField = (event) => {
    const { name, value } = event.currentTarget;
    setMetadata((current) => ({ ...current, [name]: value }));
  };

  const submit = (event) => {
    event.preventDefault();
    onSubmit(metadata);
  };

  return (
    <div className="csv-metadata-backdrop">
      <section
        className="csv-metadata-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="csv-metadata-title"
      >
        <form onSubmit={submit}>
          <header>
            <span className="eyebrow">TIME-SERIES PROVENANCE</span>
            <h2 id="csv-metadata-title">Describe the uploaded inputs</h2>
            <p>
              {fileName} · 24 hourly rows required. The tariff and grid-emissions
              timestamps in every row must identify the same interval.
            </p>
          </header>

          <div className="csv-metadata-fields">
            <label>
              IANA time zone
              <input
                name="timezone"
                value={metadata.timezone}
                onChange={updateField}
                placeholder="Europe/Berlin"
                autoComplete="off"
                required
              />
            </label>
            <label>
              Tariff unit
              <input
                name="tariff_unit"
                value={metadata.tariff_unit}
                onChange={updateField}
                placeholder="EUR/kWh"
                pattern="[A-Z]{3}/kWh"
                title="Use an ISO currency code per kWh, such as EUR/kWh."
                required
              />
            </label>
            <label className="csv-metadata-wide">
              Tariff source or URL
              <input
                name="tariff_source"
                value={metadata.tariff_source}
                onChange={updateField}
                placeholder="Supplier tariff schedule or source URL"
                maxLength={500}
                required
              />
            </label>
            <label>
              Grid-emissions unit
              <input
                name="grid_emissions_unit"
                value={metadata.grid_emissions_unit}
                onChange={updateField}
                placeholder="kgCO2/kWh"
                required
              />
            </label>
            <label className="csv-metadata-wide">
              Grid-emissions source or URL
              <input
                name="grid_emissions_source"
                value={metadata.grid_emissions_source}
                onChange={updateField}
                placeholder="Grid-factor dataset, region, and source URL"
                maxLength={500}
                required
              />
            </label>
          </div>

          <p className="csv-metadata-notice">
            Timestamps must be ISO 8601 with UTC offsets and form 24 consecutive
            one-hour intervals in the declared time zone. Source descriptions are
            caller-supplied and are not independently verified. Convert other
            units explicitly before upload.
          </p>
          {error && <p className="csv-metadata-error" role="alert">{error}</p>}

          <div className="csv-metadata-actions">
            <button type="button" className="outline-button" onClick={onCancel} disabled={busy}>
              Cancel
            </button>
            <button type="submit" className="primary-button" disabled={busy}>
              {busy ? 'Validating…' : 'Validate and import'}
            </button>
          </div>
        </form>
      </section>
    </div>
  );
}
