import { useMemo, useRef, useState } from "react";
import { api } from "../api";
import { Badge, Card, EmptyState, ErrorBanner, Modal, Notice, Spinner, useMeta } from "../components";
import { bytes, fileTone, label } from "../format";
import type { BatchDetail, FileInfo, ProcessResult, Role, TemplateSummary } from "../types";
import MappingPanel from "./MappingPanel";

export default function ImportView({ batch, onChanged }: { batch: BatchDetail; onChanged: () => Promise<unknown> }) {
  const meta = useMeta();
  const template = meta.templates.find((t) => t.id === batch.template_id);
  const [mappingFile, setMappingFile] = useState<FileInfo | null>(null);
  const [removing, setRemoving] = useState<FileInfo | null>(null);
  const [processing, setProcessing] = useState(false);
  const [result, setResult] = useState<ProcessResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const files = batch.files;
  const pending = files.filter((f) => f.status === "uploaded" || f.status === "ready").length;
  const needsMapping = files.filter((f) => f.status === "needs_mapping");

  const process = async () => {
    setProcessing(true);
    setError(null);
    try {
      const r = await api.process(batch.id);
      setResult(r);
      await onChanged();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setProcessing(false);
    }
  };

  if (!template) return <ErrorBanner error={`Template ${batch.template_id} is not installed.`} />;

  return (
    <div className="stack">
      <TemplateCard template={template} />
      <div className="grid-2">
        {(["invoice", "reference"] as Role[]).map((role) => (
          <UploadPanel key={role} batchId={batch.id} role={role} template={template} onUploaded={onChanged} />
        ))}
      </div>

      <Card
        title="Files in this batch"
        actions={
          <button className="btn btn-primary" onClick={process} disabled={processing || pending === 0}>
            {processing ? <Spinner label="Processing" /> : pending > 0 ? `Process ${pending} file${pending === 1 ? "" : "s"}` : "Nothing to process"}
          </button>
        }
      >
        <ErrorBanner error={error} onDismiss={() => setError(null)} />
        {needsMapping.length > 0 && (
          <Notice tone="warn">
            {needsMapping.length} spreadsheet{needsMapping.length === 1 ? " needs" : "s need"} a column mapping before it can be imported:{" "}
            {needsMapping.map((f, i) => (
              <span key={f.id}>
                {i > 0 && ", "}
                <button className="link" onClick={() => setMappingFile(f)}>
                  {f.original_name}
                </button>
              </span>
            ))}
            .
          </Notice>
        )}
        {result && (
          <Notice tone="good">
            Processed {result.processed_files} file{result.processed_files === 1 ? "" : "s"}. The batch now has {result.invoices} invoice
            {result.invoices === 1 ? "" : "s"} and {result.references} register row{result.references === 1 ? "" : "s"}, with{" "}
            {result.open_exception_records} record{result.open_exception_records === 1 ? "" : "s"} showing exceptions.
            {result.waiting_for_mapping.length > 0 && ` Still waiting for mapping: ${result.waiting_for_mapping.join(", ")}.`}{" "}
            <a href={`#/batches/${batch.id}/records`}>Go to records</a>
          </Notice>
        )}
        {files.length === 0 ? (
          <EmptyState title="No files uploaded yet">
            Upload supplier invoices and the purchase register above. Nothing is processed until you press Process.
          </EmptyState>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>File</th>
                <th>Used as</th>
                <th>Type</th>
                <th className="num">Size</th>
                <th>Status</th>
                <th>Details</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {files.map((f) => (
                <tr key={f.id} className={f.status === "removed" ? "row-muted" : ""}>
                  <td className="strong break">{f.original_name}</td>
                  <td>{template.roles[f.role].plural}</td>
                  <td>{(f.kind ?? "?").toUpperCase()}</td>
                  <td className="num nowrap">{bytes(f.size_bytes)}</td>
                  <td>
                    <Badge tone={fileTone(f.status)}>{label(meta.labels, "file_status", f.status)}</Badge>
                  </td>
                  <td className="small">
                    {f.status_detail}
                    {f.record_count > 0 && f.status === "processed" && f.kind !== "pdf" && ` (${f.record_count} records)`}
                  </td>
                  <td className="nowrap actions">
                    {(f.status === "needs_mapping" || f.status === "ready") && (
                      <button className="btn btn-small" onClick={() => setMappingFile(f)}>
                        {f.status === "ready" ? "Edit mapping" : "Map columns"}
                      </button>
                    )}
                    {f.status !== "removed" && f.kind && f.rejection_code !== "too_large" && (
                      <a className="btn btn-small btn-ghost" href={api.fileContentUrl(f.id)} target="_blank" rel="noreferrer">
                        {f.kind === "pdf" ? "Open" : "Download"}
                      </a>
                    )}
                    {f.status !== "removed" && (
                      <button className="btn btn-small btn-ghost danger" onClick={() => setRemoving(f)}>
                        Remove
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>

      {mappingFile && (
        <MappingPanel
          file={mappingFile}
          template={template}
          onClose={() => setMappingFile(null)}
          onConfirmed={async () => {
            setMappingFile(null);
            await onChanged();
          }}
        />
      )}
      {removing && (
        <RemoveFileModal
          file={removing}
          onClose={() => setRemoving(null)}
          onRemoved={async () => {
            setRemoving(null);
            await onChanged();
          }}
        />
      )}
    </div>
  );
}

function TemplateCard({ template }: { template: TemplateSummary }) {
  const [open, setOpen] = useState(false);
  const fieldLabel = (n: string) => template.fields.find((f) => f.name === n)?.label ?? n;
  return (
    <Card
      title={`Template: ${template.name}`}
      actions={
        <button className="btn btn-small btn-ghost" onClick={() => setOpen(!open)} aria-expanded={open}>
          {open ? "Hide details" : "Show fields, rules and matching"}
        </button>
      }
    >
      <p className="muted">{template.description}</p>
      <div className="facts">
        <div>
          <span className="fact-label">Matching identity</span>
          {template.matching.identity_fields.map(fieldLabel).join(" + ")}
        </div>
        <div>
          <span className="fact-label">Compared after identity match</span>
          {template.matching.compare.map((c) => `${fieldLabel(c.field)}${Number(c.tolerance) > 0 ? ` (±${c.tolerance})` : ""}`).join(", ")}
        </div>
        <div>
          <span className="fact-label">Default date format for spreadsheets</span>
          {template.date_order_labels[template.dates.default_order]}
        </div>
        <div>
          <span className="fact-label">Currencies</span>
          {template.currency.allowed.join(", ")}
        </div>
      </div>
      {open && (
        <div className="template-details">
          <h3>Fields</h3>
          <table className="table compact">
            <thead>
              <tr>
                <th>Field</th>
                <th>Type</th>
                <th>Required</th>
                <th>Column headings recognised (exact, after normalising case and punctuation)</th>
              </tr>
            </thead>
            <tbody>
              {template.fields.map((f) => (
                <tr key={f.name}>
                  <td className="strong">{f.label}</td>
                  <td>{f.type}</td>
                  <td>{f.required ? "Yes" : "No"}</td>
                  <td className="small">{[f.label, ...f.aliases].join(", ")}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <h3>Validation rules</h3>
          <ul className="plain">
            {template.validation_rules.map((r) => (
              <li key={r.id}>
                <strong>{r.label}</strong>{" "}
                <span className="muted small">
                  ({r.type}
                  {r.tolerance ? `, tolerance ${r.tolerance}` : ""}, {r.severity}, applies to {r.applies_to.map((x) => template.roles[x as Role].plural.toLowerCase()).join(" and ")})
                </span>
              </li>
            ))}
          </ul>
          <h3>Supported PDF invoice layouts</h3>
          <ul className="plain">
            {template.pdf_layout_details.map((l) => (
              <li key={l.id}>
                <strong>{l.name}</strong> <span className="muted small">{l.description} Dates read as {l.date_order_label}.</span>
              </li>
            ))}
          </ul>
          <p className="muted small">
            PDFs are read by deterministic text parsers for these layouts. Other layouts, scans without a text layer and damaged files are
            rejected with a reason. Supplier names are compared after removing case, punctuation and the legal suffixes{" "}
            {template.party_normalization.legal_suffixes.join(", ")}; explicit aliases:{" "}
            {Object.entries(template.party_normalization.aliases)
              .map(([k, v]) => `${v.join(", ")} = ${k}`)
              .join("; ") || "none"}
            . No fuzzy matching is used.
          </p>
          <p className="muted small">{template.synthetic_note}</p>
        </div>
      )}
    </Card>
  );
}

function UploadPanel({ batchId, role, template, onUploaded }: { batchId: number; role: Role; template: TemplateSummary; onUploaded: () => Promise<unknown> }) {
  const meta = useMeta();
  const input = useRef<HTMLInputElement>(null);
  const [drag, setDrag] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const roleDef = template.roles[role];
  const accept = useMemo(() => roleDef.accepts.map((k) => `.${k}`).join(","), [roleDef]);

  const send = async (list: FileList | File[]) => {
    const files = Array.from(list);
    if (!files.length) return;
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const out = await api.upload(batchId, role, files);
      const rejected = out.filter((f) => f.status === "rejected");
      const identical = out.filter((f) => f.identical_to);
      let msg = `Uploaded ${out.length} file${out.length === 1 ? "" : "s"}.`;
      if (rejected.length) msg += ` ${rejected.length} rejected (see the file list for reasons).`;
      if (identical.length) msg += ` ${identical.map((f) => `${f.original_name} has the same content as ${f.identical_to}`).join("; ")}.`;
      setMessage(msg);
      await onUploaded();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
      if (input.current) input.current.value = "";
    }
  };

  return (
    <Card title={roleDef.plural}>
      <p className="muted small">{roleDef.description}</p>
      <div
        className={`dropzone ${drag ? "drag" : ""}`}
        onDragOver={(e) => {
          e.preventDefault();
          setDrag(true);
        }}
        onDragLeave={() => setDrag(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDrag(false);
          send(e.dataTransfer.files);
        }}
      >
        {busy ? (
          <Spinner label="Uploading" />
        ) : (
          <>
            <span>Drop {roleDef.accepts.map((a) => a.toUpperCase()).join(", ")} files here, or</span>
            <button className="btn btn-small" onClick={() => input.current?.click()}>
              Choose files
            </button>
            <span className="muted small">Up to {meta.limits.max_upload_mb} MB each</span>
          </>
        )}
        <input ref={input} type="file" multiple accept={accept} hidden onChange={(e) => e.target.files && send(e.target.files)} />
      </div>
      <ErrorBanner error={error} onDismiss={() => setError(null)} />
      {message && <div className="muted small upload-msg">{message}</div>}
    </Card>
  );
}

function RemoveFileModal({ file, onClose, onRemoved }: { file: FileInfo; onClose: () => void; onRemoved: () => Promise<unknown> }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const run = async () => {
    setBusy(true);
    try {
      await api.removeFile(file.id);
      await onRemoved();
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  };
  return (
    <Modal
      title="Remove file"
      onClose={onClose}
      footer={
        <>
          <button className="btn btn-ghost" onClick={onClose}>
            Cancel
          </button>
          <button className="btn btn-danger" disabled={busy} onClick={run}>
            {busy ? <Spinner label="Removing" /> : "Remove file"}
          </button>
        </>
      }
    >
      <ErrorBanner error={error} />
      <p>
        Remove <strong>{file.original_name}</strong> from this batch? Records imported from it are deleted and matching is rerun. The file
        stays in the list as removed, so every upload remains accounted for.
      </p>
    </Modal>
  );
}
