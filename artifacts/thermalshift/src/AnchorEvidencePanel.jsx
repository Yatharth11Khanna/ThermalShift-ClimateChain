import { useEffect, useState } from 'react';
import { AlertTriangle, CheckCircle2, ExternalLink, Link2, ShieldCheck } from 'lucide-react';
import { useQueryClient } from '@tanstack/react-query';
import {
  getGetThermalShiftAnchorByReportHashQueryKey,
  useAnchorThermalShiftReport,
  useGetThermalShiftAnchorStatus,
  useGetThermalShiftAnchorByReportHash,
  useVerifyThermalShiftAnchor,
} from '@workspace/api-client-react';
import './anchor-evidence.css';

const detailText = (error, fallback) => {
  const detail = error?.response?.data?.detail;
  if (Array.isArray(detail)) {
    return detail.map((item) => item?.msg || String(item)).join('; ');
  }
  return (typeof detail === 'string' && detail) || error?.message || fallback;
};

const statusLabel = (status) => {
  if (status === 'confirmed') return 'Confirmed on Sepolia';
  if (status === 'submission_unknown') return 'Submission status unknown';
  if (status === 'rejected') return 'Submission rejected';
  if (status === 'failed') return 'Transaction failed';
  if (status === 'mismatch') return 'Transaction mismatch';
  return 'Pending confirmation';
};

export default function AnchorEvidencePanel({ report }) {
  const statusQuery = useGetThermalShiftAnchorStatus();
  const reportHash = report?.evidence?.report_hash;
  const anchorQueryKey = getGetThermalShiftAnchorByReportHashQueryKey(reportHash ?? '');
  const anchorLookup = useGetThermalShiftAnchorByReportHash(reportHash ?? '', {
    query: {
      enabled: Boolean(reportHash),
      queryKey: anchorQueryKey,
      retry: false,
      refetchOnMount: 'always',
    },
  });
  const anchorMutation = useAnchorThermalShiftReport();
  const verifyMutation = useVerifyThermalShiftAnchor();
  const queryClient = useQueryClient();
  const [record, setRecord] = useState(null);
  const [verification, setVerification] = useState(null);
  const [actionError, setActionError] = useState('');
  const status = statusQuery.data;

  useEffect(() => {
    setRecord(anchorLookup.data?.report_hash === reportHash ? anchorLookup.data : null);
    setVerification(null);
    setActionError('');
  }, [reportHash, anchorLookup.data]);

  const submitAnchor = async () => {
    if (!report || !reportHash || !status?.ready) return;
    setActionError('');
    setVerification(null);
    try {
      const result = await anchorMutation.mutateAsync({
        data: { report, report_hash: reportHash },
      });
      setRecord(result);
      queryClient.setQueryData(anchorQueryKey, result);
    } catch (error) {
      setActionError(detailText(error, 'Could not submit this report hash to Sepolia.'));
    }
  };

  const verifyAnchor = async () => {
    if (!report || !record?.transaction_hash) return;
    setActionError('');
    try {
      const result = await verifyMutation.mutateAsync({
        data: { report, transaction_hash: record.transaction_hash },
      });
      setRecord(result);
      queryClient.setQueryData(anchorQueryKey, result);
      setVerification(result);
    } catch (error) {
      setActionError(detailText(error, 'Could not verify the transaction on Sepolia.'));
    }
  };

  const missing = status?.missing_configuration ?? [];
  const readiness = status?.write_enabled === false
    ? 'Writes disabled'
    : status?.ready
      ? 'Ready'
      : statusQuery.isLoading
        ? 'Checking setup'
        : status?.enabled && status?.network_available === false
          ? 'RPC unavailable'
          : status?.enabled && status?.configured
            ? 'Needs test ETH'
            : 'Not configured';

  return (
    <section className="panel anchor-panel" aria-labelledby="anchor-title" data-testid="panel-testnet-anchor">
      <div className="anchor-panel-heading">
        <div className="anchor-icon"><Link2 size={20} /></div>
        <div>
          <h2 id="anchor-title">Public testnet anchor</h2>
          <p>Ethereum Sepolia · chain ID 11155111 · no contract deployed</p>
        </div>
        <span className={`anchor-readiness ${status?.ready && status?.write_enabled !== false ? 'is-ready' : ''}`} data-testid="status-anchor-readiness">
          {readiness}
        </span>
      </div>

      <p className="anchor-description">
        Public anchoring writes are disabled until caller authorization is implemented.
        Status, lookup, and on-chain verification remain available.
      </p>

      {!reportHash && (
        <div className="anchor-inline-note">
          Run an optimization to create a report hash before anchoring.
        </div>
      )}

      {statusQuery.isError && (
        <div className="anchor-inline-note is-warning">
          The API could not check testnet readiness. No transaction has been submitted.
        </div>
      )}

      {status?.write_enabled === true && missing.length > 0 && (
        <div className="anchor-setup">
          <b>Setup still required</b>
          <ul>
            {missing.map((item) => <li key={item} data-testid={`item-anchor-setup-${item.replace(/[^a-z0-9]+/gi, '-').toLowerCase()}`}>{item}</li>)}
          </ul>
          <small>
            Keep the RPC URL and dedicated testnet private key in server-side Replit
            Secrets. Never put them in the browser or source files.
          </small>
        </div>
      )}
      {status?.status_error && (
        <div className="anchor-inline-note is-warning">{status.status_error}</div>
      )}

      <div className="anchor-actions">
        <button
          className="primary-button"
          data-testid="button-anchor-report-hash"
          onClick={submitAnchor}
          disabled={!reportHash || status?.write_enabled !== true || !status?.ready || anchorMutation.isPending}
        >
          <Link2 size={16} />
          {anchorMutation.isPending ? 'Submitting…' : 'Anchor report hash'}
        </button>
        {record?.transaction_hash && (
          <button
            className="outline-button"
            data-testid="button-verify-on-sepolia"
            onClick={verifyAnchor}
            disabled={verifyMutation.isPending}
          >
            <ShieldCheck size={16} />
            {verifyMutation.isPending ? 'Checking…' : 'Verify on Sepolia'}
          </button>
        )}
      </div>

      {actionError && (
        <div className="anchor-inline-note is-warning" role="alert" data-testid="status-anchor-error">
          <AlertTriangle size={15} /> {actionError}
        </div>
      )}

      {record && (
        <div className={`anchor-record status-${record.status}`} data-testid="record-testnet-anchor">
          <div className="anchor-record-title">
            {record.status === 'confirmed'
              ? <CheckCircle2 size={17} />
              : <AlertTriangle size={17} />}
            <b>{statusLabel(record.status)}</b>
            <span>
              {record.confirmations}/{record.confirmations_required} confirmations
            </span>
          </div>
          <dl>
            <div><dt>Transaction</dt><dd><code data-testid="text-anchor-transaction-hash">{record.transaction_hash}</code></dd></div>
            <div><dt>Destination</dt><dd><code data-testid="text-anchor-destination">{record.destination_address}</code></dd></div>
          </dl>
          {record.last_error && <p className="anchor-last-error">{record.last_error}</p>}
          {record.explorer_url && (
            <a href={record.explorer_url} target="_blank" rel="noreferrer" data-testid="link-anchor-explorer">
              View transaction on Etherscan <ExternalLink size={14} />
            </a>
          )}
        </div>
      )}

      {verification && (
        <div className={`anchor-verification ${verification.valid === true ? 'is-valid' : ''}`} data-testid="status-anchor-verification">
          <b>
            {verification.valid === true
              ? 'On-chain verification passed'
              : verification.valid === false
                ? 'Verification mismatch'
                : 'Not confirmed yet'}
          </b>
          <p>{verification.note}</p>
        </div>
      )}

      <div className="anchor-trust-note">
        A confirmed transaction proves only that these bytes were included on Sepolia.
        It does not prove who supplied the data, validate the thermal model, or establish
        real-world energy or emissions savings.
      </div>
      <div className="anchor-safety-note">
        <AlertTriangle size={15} />
        <span>
          Use a dedicated faucet-funded wallet only. Keep anchoring disabled on a
          publicly accessible deployment until access controls are added.
        </span>
      </div>
    </section>
  );
}
