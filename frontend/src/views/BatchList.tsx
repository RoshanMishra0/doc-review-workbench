import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { Badge, Card, EmptyState, ErrorBanner, Modal, Notice, Progress, Spinner, useMeta } from "../components";
import { dateTime } from "../format";
import { navigate } from "../router";
import type { BatchSummary, Sample } from "../types";

export default function BatchList() {
  const meta = useMeta();
  const [batches, setBatches] = useState<BatchSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showNew, setShowNew] = useState(false);
  const [showSamples, setShowSamples] = useState(false);
  const [deleting, setDeleting] = useState<BatchSummary | null>(null);

  const load = useCallback(() => {
    setError(null);
    api.batches().then(setBatches).catch((e: Error) => setError(e.message));
  }, []);
  useEffect(load, [load]);

  const actions = (
    <>
      <button className="btn" onClick={() => setShowSamples(true)}>
        Load sample dataset
      </button>
      <button className="btn btn-primary" onClick={() => setShowNew(true)}>
        New batch
      </button>
    </>
  );

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>Batches</h1>
          <p className="muted">
            Each batch holds uploaded documents, a reference spreadsheet, the extracted records and every review decision.
          </p>
        </div>
        <div className="page-actions">{actions}</div>
      </div>
      <ErrorBanner error={error} onRetry={load} />
      {!batches && !error && <Spinner label="Loading batches" />}
      {batches && batches.length === 0 && (
        <Card>
          <EmptyState title="No batches yet" actions={actions}>
            Start a new batch and upload your own files, or load the synthetic sample dataset to see the full workflow with
            fictional companies.
          </EmptyState>
        </Card>
      )}
      {batches && batches.length > 0 && (
        <Card>
          <table className="table">
            <thead>
              <tr>
                <th>Batch</th>
                <th>Created</th>
                <th>Files</th>
                <th className="num">Invoices</th>
                <th className="num">Register rows</th>
                <th className="num">Open exceptions</th>
                <th>Invoices reviewed</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {batches.map((b) => (
                <tr key={b.id} className="clickable" onClick={() => navigate(`/batches/${b.id}`)}>
                  <td>
                    <a href={`#/batches/${b.id}`} onClick={(e) => e.stopPropagation()} className="strong">
                      {b.name}
                    </a>
                    <div className="muted small">
                      {b.template_name}
                      {b.sample_id && (
                        <>
                          {" "}
                          · <span className="tag tag-synthetic">Synthetic</span>
                        </>
                      )}
                    </div>
                  </td>
                  <td className="nowrap">{dateTime(b.created_at)}</td>
                  <td>
                    {b.counts.files.total}
                    {b.counts.rejected_files > 0 && (
                      <>
                        {" "}
                        <Badge tone="bad">{b.counts.rejected_files} rejected</Badge>
                      </>
                    )}
                    {b.counts.needs_mapping > 0 && (
                      <>
                        {" "}
                        <Badge tone="warn">{b.counts.needs_mapping} need mapping</Badge>
                      </>
                    )}
                    {b.counts.pending_files > 0 && (
                      <>
                        {" "}
                        <Badge tone="info">{b.counts.pending_files} not processed</Badge>
                      </>
                    )}
                  </td>
                  <td className="num">{b.counts.invoices}</td>
                  <td className="num">{b.counts.references}</td>
                  <td className="num">{b.counts.open_exception_records > 0 ? <Badge tone="warn">{b.counts.open_exception_records}</Badge> : 0}</td>
                  <td>
                    <Progress value={b.counts.progress.decided} total={b.counts.progress.total} />
                  </td>
                  <td className="nowrap" onClick={(e) => e.stopPropagation()}>
                    <button className="btn btn-small btn-ghost danger" onClick={() => setDeleting(b)}>
                      Delete
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}
      {showNew && <NewBatchModal templates={meta.templates.map((t) => ({ id: t.id, name: t.name }))} onClose={() => setShowNew(false)} />}
      {showSamples && <SampleModal onClose={() => setShowSamples(false)} />}
      {deleting && (
        <DeleteModal
          batch={deleting}
          onClose={() => setDeleting(null)}
          onDeleted={() => {
            setDeleting(null);
            load();
          }}
        />
      )}
    </div>
  );
}

function NewBatchModal({ templates, onClose }: { templates: { id: string; name: string }[]; onClose: () => void }) {
  const [name, setName] = useState("");
  const [templateId, setTemplateId] = useState(templates[0]?.id ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      const b = await api.createBatch(name, templateId);
      navigate(`/batches/${b.id}/import`);
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  };
  return (
    <Modal
      title="New batch"
      onClose={onClose}
      footer={
        <>
          <button className="btn btn-ghost" onClick={onClose}>
            Cancel
          </button>
          <button className="btn btn-primary" disabled={busy || !name.trim()} onClick={submit}>
            {busy ? <Spinner label="Creating" /> : "Create and go to import"}
          </button>
        </>
      }
    >
      <ErrorBanner error={error} />
      <label className="field">
        <span>Batch name</span>
        <input
          autoFocus
          value={name}
          maxLength={120}
          placeholder="e.g. March 2025 supplier invoices"
          onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && name.trim() && submit()}
        />
      </label>
      <label className="field">
        <span>Workflow template</span>
        <select value={templateId} onChange={(e) => setTemplateId(e.target.value)}>
          {templates.map((t) => (
            <option key={t.id} value={t.id}>
              {t.name}
            </option>
          ))}
        </select>
      </label>
    </Modal>
  );
}

function SampleModal({ onClose }: { onClose: () => void }) {
  const [samples, setSamples] = useState<Sample[] | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    api.samples().then(setSamples).catch((e: Error) => setError(e.message));
  }, []);
  const load = async (id: string) => {
    setBusy(id);
    setError(null);
    try {
      const r = await api.loadSample(id);
      navigate(`/batches/${r.batch_id}/${r.waiting_for_mapping.length ? "import" : "records"}`);
    } catch (e) {
      setError((e as Error).message);
      setBusy(null);
    }
  };
  return (
    <Modal title="Load sample dataset" onClose={onClose}>
      <Notice>
        The sample files are synthetic: fictional companies and figures. Loading creates a new batch and submits the files through
        the same upload, mapping and processing pipeline as your own files.
      </Notice>
      <ErrorBanner error={error} />
      {!samples && !error && <Spinner label="Loading sample list" />}
      <div className="sample-list">
        {samples?.map((s) => (
          <div key={s.id} className="sample">
            <div>
              <div className="strong">{s.name}</div>
              <div className="muted small">{s.description}</div>
              <div className="muted small">{s.file_count} files</div>
            </div>
            <button className="btn btn-primary" disabled={busy !== null} onClick={() => load(s.id)}>
              {busy === s.id ? <Spinner label="Loading and processing" /> : "Load"}
            </button>
          </div>
        ))}
      </div>
    </Modal>
  );
}

function DeleteModal({ batch, onClose, onDeleted }: { batch: BatchSummary; onClose: () => void; onDeleted: () => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const run = async () => {
    setBusy(true);
    try {
      await api.deleteBatch(batch.id);
      onDeleted();
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  };
  return (
    <Modal
      title="Delete batch"
      onClose={onClose}
      footer={
        <>
          <button className="btn btn-ghost" onClick={onClose}>
            Cancel
          </button>
          <button className="btn btn-danger" disabled={busy} onClick={run}>
            {busy ? <Spinner label="Deleting" /> : "Delete permanently"}
          </button>
        </>
      }
    >
      <ErrorBanner error={error} />
      <p>
        Delete <strong>{batch.name}</strong>? Its records, review history and the app's stored copies of its uploaded files are removed.
        This cannot be undone. Your original files elsewhere on disk are not touched.
      </p>
    </Modal>
  );
}
