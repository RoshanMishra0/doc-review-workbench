import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { Badge, Card, EmptyState, ErrorBanner, Notice, Spinner, roleWords, useMeta, useTemplate } from "../components";
import { ACTION_LABELS, dateTime, fieldTone, label, matchTone, reviewTone, validationTone } from "../format";
import { navigate, withQuery } from "../router";
import type { BatchDetail, Evidence, RecordDetail, RecordSummary } from "../types";
import { filterQuery, filtersFrom } from "./RecordsView";

export default function ReviewView({
  batch,
  recordId,
  query,
  onChanged,
}: {
  batch: BatchDetail;
  recordId: number | null;
  query: URLSearchParams;
  onChanged: () => Promise<unknown>;
}) {
  const filters = useMemo(() => filtersFrom(query), [query]);
  const [list, setList] = useState<RecordSummary[] | null>(null);
  const [listError, setListError] = useState<string | null>(null);
  const key = JSON.stringify(filters);

  useEffect(() => {
    const f = JSON.parse(key) as Record<string, string>;
    api
      .records(batch.id, { ...f, corrected: f.corrected === "1" ? true : undefined })
      .then(setList)
      .catch((e: Error) => setListError(e.message));
  }, [batch.id, key, batch.updated_at]);

  // Without a record id, open the first record awaiting review that has issues.
  useEffect(() => {
    if (recordId || !list) return;
    const first = list.find((r) => r.review_status === "awaiting_review" && r.issue_count > 0) ?? list[0];
    if (first) navigate(withQuery(`/batches/${batch.id}/records/${first.id}`, filterQuery(filters)));
  }, [recordId, list, batch.id, filters]);

  if (!recordId) {
    if (listError) return <ErrorBanner error={listError} />;
    if (list && list.length === 0)
      return (
        <Card>
          <EmptyState title="Nothing to review">There are no records in this view. Process files on the Import tab first.</EmptyState>
        </Card>
      );
    return <Spinner label="Finding a record to review" />;
  }

  const ids = list?.map((r) => r.id) ?? [];
  const pos = ids.indexOf(recordId);
  const go = (id: number) => navigate(withQuery(`/batches/${batch.id}/records/${id}`, filterQuery(filters)));

  return (
    <RecordReview
      key={recordId}
      batchId={batch.id}
      recordId={recordId}
      position={pos >= 0 ? { index: pos, total: ids.length, prev: ids[pos - 1], next: ids[pos + 1] } : null}
      backHref={withQuery(`#/batches/${batch.id}/records`, filterQuery(filters))}
      go={go}
      onChanged={onChanged}
    />
  );
}

interface Position {
  index: number;
  total: number;
  prev?: number;
  next?: number;
}

function RecordReview({
  batchId,
  recordId,
  position,
  backHref,
  go,
  onChanged,
}: {
  batchId: number;
  recordId: number;
  position: Position | null;
  backHref: string;
  go: (id: number) => void;
  onChanged: () => Promise<unknown>;
}) {
  const meta = useMeta();
  const [rec, setRec] = useState<RecordDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [flash, setFlash] = useState<string | null>(null);
  const [highlight, setHighlight] = useState<string | null>(null);

  const load = useCallback(() => {
    setError(null);
    api
      .record(recordId)
      .then(setRec)
      .catch((e: Error) => setError(e.message));
  }, [recordId]);
  useEffect(load, [load]);

  const run = async (name: string, fn: () => Promise<RecordDetail>, message?: string) => {
    setBusy(name);
    setActionError(null);
    setFlash(null);
    try {
      const updated = await fn();
      setRec(updated);
      if (message) setFlash(message);
      await onChanged();
      return true;
    } catch (e) {
      setActionError((e as Error).message);
      return false;
    } finally {
      setBusy(null);
    }
  };

  if (error) return <ErrorBanner error={error} onRetry={load} />;
  if (!rec) return <Spinner label="Loading record" />;

  const errors = rec.issues.filter((i) => i.severity === "error");
  const tLabels = meta.templates.find((t) => t.id === rec.template_id)?.labels ?? meta.labels;
  return (
    <div className="stack">
      <div className="review-head">
        <div>
          <a href={backHref} className="small">
            Back to records
          </a>
          <h2>
            #{rec.id} {rec.source_ref}
          </h2>
          <div className="badges">
            <span className="muted small">{rec.role_label}</span>
            <Badge tone={validationTone(rec.validation_status)}>{label(tLabels, "validation_status", rec.validation_status)}</Badge>
            <Badge tone={matchTone(rec.match_status)}>{label(tLabels, "match_status", rec.match_status)}</Badge>
            <Badge tone={reviewTone(rec.review_status)}>{label(tLabels, "review_status", rec.review_status)}</Badge>
            {rec.corrected && <Badge tone="accent">User corrected</Badge>}
          </div>
        </div>
        {position && (
          <div className="pager">
            <button className="btn btn-small" disabled={!position.prev} onClick={() => position.prev && go(position.prev)}>
              Previous
            </button>
            <span className="muted small">
              {position.index + 1} of {position.total}
            </span>
            <button className="btn btn-small" disabled={!position.next} onClick={() => position.next && go(position.next)}>
              Next
            </button>
          </div>
        )}
      </div>
      {flash && <Notice tone="good">{flash}</Notice>}
      <ErrorBanner error={actionError} onDismiss={() => setActionError(null)} />

      <div className="review-grid">
        <div className="stack">
          <FieldsCard rec={rec} busy={busy} onHighlight={setHighlight} onSave={(values, note) =>
            run("correct", async () => {
              const r = await api.correct(rec.id, values, note);
              const withdrawn = r.summary.approvals_withdrawn ?? [];
              setFlash(
                `Saved ${r.changed_fields.length} correction${r.changed_fields.length === 1 ? "" : "s"} and reran validation and matching for the batch.` +
                  (withdrawn.length ? ` Approval withdrawn for record${withdrawn.length === 1 ? "" : "s"} ${withdrawn.map((x) => `#${x}`).join(", ")}.` : ""),
              );
              return r.record;
            })
          } />
          <ChecksCard rec={rec} />
          <MatchCard rec={rec} batchId={batchId} busy={busy} run={run} />
          <DecisionCard rec={rec} errors={errors.length} busy={busy} run={run} />
          <HistoryCard rec={rec} />
        </div>
        <div className="stack sticky">
          <SourceCard rec={rec} highlight={highlight} />
        </div>
      </div>
    </div>
  );
}

function FieldsCard({
  rec,
  busy,
  onSave,
  onHighlight,
}: {
  rec: RecordDetail;
  busy: string | null;
  onSave: (values: Record<string, string | null>, note: string | null) => Promise<boolean>;
  onHighlight: (field: string | null) => void;
}) {
  const meta = useMeta();
  const tLabels = meta.templates.find((t) => t.id === rec.template_id)?.labels ?? meta.labels;
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [note, setNote] = useState("");

  const start = () => {
    const d: Record<string, string> = {};
    for (const f of rec.field_defs) d[f.name] = rec.fields[f.name]?.current ?? "";
    setDraft(d);
    setNote("");
    setEditing(true);
  };
  const changed = rec.field_defs.filter((f) => (draft[f.name] ?? "").trim() !== (rec.fields[f.name]?.current ?? ""));
  const save = async () => {
    const values: Record<string, string | null> = {};
    for (const f of changed) values[f.name] = draft[f.name].trim() || null;
    if (await onSave(values, note.trim() || null)) setEditing(false);
  };
  const revert = (name: string) => onSave({ [name]: null }, "Reverted to the extracted value");

  return (
    <Card
      title="Fields"
      actions={
        editing ? (
          <>
            <button className="btn btn-small btn-ghost" onClick={() => setEditing(false)}>
              Cancel
            </button>
            <button className="btn btn-small btn-primary" disabled={!changed.length || busy !== null} onClick={save}>
              {busy === "correct" ? <Spinner label="Rerunning checks" /> : `Save ${changed.length || ""} and rerun checks`}
            </button>
          </>
        ) : (
          <button className="btn btn-small" onClick={start}>
            Correct values
          </button>
        )
      }
    >
      <div className="muted small">
        {rec.extraction_method}. Dates read as {rec.date_order_label}. Extracted values are kept unchanged; corrections are stored separately.
      </div>
      <table className="table compact fields">
        <thead>
          <tr>
            <th>Field</th>
            <th>Extracted</th>
            <th>{editing ? "Corrected value" : "Current"}</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          {rec.field_defs.map((fd) => {
            const f = rec.fields[fd.name];
            if (!f) return null;
            return (
              <tr key={fd.name} onMouseEnter={() => onHighlight(fd.name)} onMouseLeave={() => onHighlight(null)} className={f.error ? "row-error" : ""}>
                <td className="strong">{fd.label}</td>
                <td className="mono small">{f.original ?? <span className="value-missing">Not found</span>}</td>
                <td>
                  {editing ? (
                    <input
                      value={draft[fd.name] ?? ""}
                      onChange={(e) => setDraft({ ...draft, [fd.name]: e.target.value })}
                      aria-label={`Corrected ${fd.label}`}
                      className={(draft[fd.name] ?? "").trim() !== (f.current ?? "") ? "changed" : ""}
                    />
                  ) : f.current === null ? (
                    <span className="value-missing">Missing</span>
                  ) : (
                    <>
                      <span className={f.error ? "value-invalid" : ""}>{f.display ?? f.current}</span>
                      {f.error && <div className="tiny error-text">{f.error}</div>}
                      {f.status === "user_corrected" && f.display !== f.current && <div className="tiny muted">typed as "{f.current}"</div>}
                    </>
                  )}
                </td>
                <td className="nowrap">
                  <Badge tone={fieldTone(f.status)}>{label(tLabels, "field_status", f.status)}</Badge>
                  {f.status === "user_corrected" && !editing && (
                    <button className="link tiny" disabled={busy !== null} onClick={() => revert(fd.name)}>
                      Revert
                    </button>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {editing && (
        <label className="field">
          <span>Note for the history (optional)</span>
          <input value={note} maxLength={2000} onChange={(e) => setNote(e.target.value)} placeholder="Where the correct value came from" />
        </label>
      )}
    </Card>
  );
}

function ChecksCard({ rec }: { rec: RecordDetail }) {
  const scope = useTemplate(rec.template_id).synthetic_note;
  const issues = rec.checks.filter((c) => c.status === "issue");
  const others = rec.checks.filter((c) => c.status !== "issue");
  return (
    <Card title={`Checks (${issues.length} issue${issues.length === 1 ? "" : "s"})`}>
      <ul className="checks">
        {[...issues, ...others].map((c, i) => (
          <li key={`${c.rule_id}-${c.field}-${i}`} className={`check check-${c.status === "issue" ? c.severity : c.status}`}>
            <span className="check-icon" aria-hidden="true">
              {c.status === "passed" ? "OK" : c.status === "not_checked" ? "--" : c.severity === "error" ? "!!" : "!"}
            </span>
            <div>
              <div className="strong small">{c.label}</div>
              <div className="small">{c.message}</div>
            </div>
          </li>
        ))}
      </ul>
      <div className="muted tiny">
        {scope}
      </div>
    </Card>
  );
}

function MatchCard({
  rec,
  batchId,
  busy,
  run,
}: {
  rec: RecordDetail;
  batchId: number;
  busy: string | null;
  run: (name: string, fn: () => Promise<RecordDetail>, message?: string) => Promise<boolean>;
}) {
  const meta = useMeta();
  const tLabels = meta.templates.find((t) => t.id === rec.template_id)?.labels ?? meta.labels;
  const m = rec.match;
  const partner = rec.partner;
  const template = meta.templates.find((t) => t.id === rec.template_id)!;
  const w = roleWords(template);
  const extraCols = (template?.summary_columns ?? []).slice(2);
  return (
    <Card title="Matching">
      <div className="badges">
        <Badge tone={matchTone(m.status)}>{label(tLabels, "match_status", m.status)}</Badge>
        {m.method === "manual_link" && <Badge tone="accent">Linked by a reviewer</Badge>}
      </div>
      <ul className="plain explanation">
        {m.explanation.map((e, i) => (
          <li key={i}>{e}</li>
        ))}
      </ul>
      {m.comparisons.length > 0 && (
        <table className="table compact">
          <thead>
            <tr>
              <th>Field</th>
              <th>{rec.role === "invoice" ? `This ${w.rec}` : "This row"}</th>
              <th>{rec.role === "invoice" ? w.RefRow : w.Rec}</th>
              <th>Result</th>
            </tr>
          </thead>
          <tbody>
            {m.comparisons.map((c) => (
              <tr key={c.field} className={c.status === "different" ? "row-error" : ""}>
                <td>{c.label}</td>
                <td className="mono small">{c.record_value ?? <span className="value-missing">Missing</span>}</td>
                <td className="mono small">{c.reference_value ?? <span className="value-missing">Missing</span>}</td>
                <td className="small">
                  {c.status === "equal" && "Same"}
                  {c.status === "within_tolerance" && `Within tolerance (${c.difference})`}
                  {c.status === "different" && <span className="error-text">Differs by {c.difference}</span>}
                  {c.status === "not_comparable" && "Cannot compare"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {m.hints.length > 0 && (
        <div className="hints">
          <div className="strong small">Where to look (not used for matching)</div>
          <ul className="plain small">
            {m.hints.map((h, i) => (
              <li key={i}>{h}</li>
            ))}
          </ul>
        </div>
      )}
      {partner && (
        <div className="partner small">
          Paired record: <a href={`#/batches/${batchId}/records/${partner.id}`}>#{partner.id} {partner.source_ref}</a>
          {rec.manual_link && (
            <button
              className="btn btn-small btn-ghost"
              disabled={busy !== null}
              onClick={() => run("unlink", () => api.unlink(rec.id), "Manual link removed and matching rerun.")}
            >
              Remove manual link
            </button>
          )}
        </div>
      )}
      {m.status === "ambiguous" && rec.candidates.length > 0 && (
        <div className="candidates">
          <div className="strong small">
            Possible {rec.role === "invoice" ? `${w.refRow}s` : `${w.rec}s`} with the same identity. Amounts are not used to choose.
          </div>
          <table className="table compact">
            <thead>
              <tr>
                <th>Record</th>
                {extraCols.map((c) => (
                  <th key={c.name}>{c.label}</th>
                ))}
                <th />
              </tr>
            </thead>
            <tbody>
              {rec.candidates.map((c) => (
                <tr key={c.id}>
                  <td className="small">
                    <a href={`#/batches/${batchId}/records/${c.id}`}>#{c.id}</a> {c.source_ref}
                  </td>
                  {extraCols.map((col) => (
                    <td key={col.name} className="small nowrap">
                      {c.fields[col.name]?.display ?? c.fields[col.name]?.current ?? "-"}
                    </td>
                  ))}
                  <td>
                    {rec.review_status !== "excluded" && c.review_status !== "excluded" && (
                      <button
                        className="btn btn-small"
                        disabled={busy !== null}
                        onClick={() => run("link", () => api.link(rec.id, c.id, null), `Linked to #${c.id} and reran matching.`)}
                      >
                        Link this {rec.role === "invoice" ? "row" : w.rec}
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="muted tiny">For a duplicate {w.rec}, excluding the extra copy is usually the right fix.</div>
        </div>
      )}
    </Card>
  );
}

function DecisionCard({
  rec,
  errors,
  busy,
  run,
}: {
  rec: RecordDetail;
  errors: number;
  busy: string | null;
  run: (name: string, fn: () => Promise<RecordDetail>, message?: string) => Promise<boolean>;
}) {
  const meta = useMeta();
  const tLabels = meta.templates.find((t) => t.id === rec.template_id)?.labels ?? meta.labels;
  const [text, setText] = useState("");
  const status = rec.review_status;
  const act = async (name: string, fn: () => Promise<RecordDetail>, message: string) => {
    if (await run(name, fn, message)) setText("");
  };
  return (
    <Card title="Review decision">
      <div className="small">
        Status: <Badge tone={reviewTone(status)}>{label(tLabels, "review_status", status)}</Badge>
        {rec.review_reason && <span className="muted"> · {rec.review_reason}</span>}
        {rec.reviewed_at && <span className="muted"> · {dateTime(rec.reviewed_at)}</span>}
      </div>
      {status === "awaiting_review" && errors > 0 && (
        <Notice tone="warn">
          This record has {errors} open issue{errors === 1 ? "" : "s"}. Correct it, exclude it with a reason, or approve it with a note that explains
          why.
        </Notice>
      )}
      <label className="field">
        <span>{status === "awaiting_review" ? "Note or reason" : "Note"}</span>
        <textarea rows={2} value={text} maxLength={2000} onChange={(e) => setText(e.target.value)} placeholder="Visible in the review history and export" />
      </label>
      <div className="button-row">
        {status === "awaiting_review" && (
          <>
            <button
              className="btn btn-primary"
              disabled={busy !== null || (errors > 0 && !text.trim())}
              title={errors > 0 && !text.trim() ? "Add a note to approve a record with open issues" : undefined}
              onClick={() => act("approve", () => api.approve(rec.id, text.trim() || null), "Approved.")}
            >
              {busy === "approve" ? <Spinner label="Approving" /> : errors > 0 ? "Approve with note" : "Approve"}
            </button>
            <button
              className="btn"
              disabled={busy !== null || !text.trim()}
              title={!text.trim() ? "Write the reason for excluding first" : undefined}
              onClick={() => act("exclude", () => api.exclude(rec.id, text.trim()), "Excluded. Matching was rerun for the batch.")}
            >
              {busy === "exclude" ? <Spinner label="Excluding" /> : "Exclude with reason"}
            </button>
          </>
        )}
        {status !== "awaiting_review" && (
          <button className="btn" disabled={busy !== null} onClick={() => act("reopen", () => api.reopen(rec.id, text.trim() || null), "Reopened for review.")}>
            {busy === "reopen" ? <Spinner label="Reopening" /> : "Reopen"}
          </button>
        )}
        <button className="btn btn-ghost" disabled={busy !== null || !text.trim()} onClick={() => act("note", () => api.note(rec.id, text.trim()), "Note added.")}>
          Add note only
        </button>
      </div>
    </Card>
  );
}

function HistoryCard({ rec }: { rec: RecordDetail }) {
  const meta = useMeta();
  const fieldLabel = (n: string | null) => (n ? rec.field_defs.find((f) => f.name === n)?.label ?? n : "");
  return (
    <Card title="History">
      {rec.history.length === 0 ? (
        <div className="muted small">No corrections or decisions yet. Extracted on {dateTime(rec.updated_at)}.</div>
      ) : (
        <ol className="timeline">
          {rec.history.map((h) => (
            <li key={h.id}>
              <div className="small">
                <strong>{ACTION_LABELS[h.action] ?? h.action}</strong>
                {h.field && <> · {fieldLabel(h.field)}</>}
                <span className="muted"> · {h.actor} · {dateTime(h.created_at)}</span>
              </div>
              {(h.old_value !== null || h.new_value !== null) && h.action !== "note" && (
                <div className="tiny mono">
                  {h.old_value ?? "(empty)"} {"->"} {h.new_value ?? "(empty)"}
                </div>
              )}
              {h.note && <div className="tiny">{h.note}</div>}
            </li>
          ))}
        </ol>
      )}
      <div className="muted tiny">Statuses shown: {Object.values(meta.labels.field_status).join(", ")}. No confidence scores are produced.</div>
    </Card>
  );
}

function SourceCard({ rec, highlight }: { rec: RecordDetail; highlight: string | null }) {
  const evidence = useMemo(() => {
    const byLine = new Map<string, string[]>();
    const byColumn = new Map<string, string>();
    for (const fd of rec.field_defs) {
      const ev: Evidence | null | undefined = rec.extracted[fd.name]?.evidence;
      if (!ev) continue;
      if (ev.page && ev.line) {
        const k = `${ev.page}:${ev.line}`;
        byLine.set(k, [...(byLine.get(k) ?? []), fd.name]);
      }
      if (ev.column) byColumn.set(ev.column, fd.name);
    }
    return { byLine, byColumn };
  }, [rec]);
  const fieldLabel = (n: string) => rec.field_defs.find((f) => f.name === n)?.label ?? n;

  return (
    <Card
      title="Source evidence"
      actions={
        <a className="btn btn-small" href={api.fileContentUrl(rec.file_id)} target="_blank" rel="noreferrer">
          {rec.file_kind === "pdf" ? "Open original PDF" : "Download original file"}
        </a>
      }
    >
      <div className="muted small">
        {rec.file_name}
        {rec.file_kind === "pdf" ? " · text layer as read by the parser; highlighted lines produced field values" : " · the source row; highlighted cells are mapped"}
      </div>
      {rec.notes.length > 0 && (
        <Notice tone="warn">
          {rec.notes.map((n, i) => (
            <div key={i}>{n}</div>
          ))}
        </Notice>
      )}
      {rec.file_kind === "pdf" &&
        rec.pages.map((p) => (
          <div key={p.page_no} className="page-text">
            <div className="tiny muted">Page {p.page_no}</div>
            <pre>
              {p.text.split("\n").map((line, i) => {
                const fields = evidence.byLine.get(`${p.page_no}:${i + 1}`) ?? [];
                const hot = highlight !== null && fields.includes(highlight);
                return (
                  <div key={i} className={`line ${fields.length ? "evidence" : ""} ${hot ? "hot" : ""}`}>
                    <span className="ln">{i + 1}</span>
                    <span className="lt">{line || " "}</span>
                    {fields.length > 0 && <span className="lf">{fields.map(fieldLabel).join(", ")}</span>}
                  </div>
                );
              })}
            </pre>
          </div>
        ))}
      {rec.source_cells && (
        <table className="table compact source-row">
          <tbody>
            {Object.entries(rec.source_cells).map(([col, value]) => {
              const field = evidence.byColumn.get(col);
              const cellRef = field ? rec.extracted[field]?.evidence?.cell : undefined;
              return (
                <tr key={col} className={`${field ? "evidence" : ""} ${field && field === highlight ? "hot" : ""}`}>
                  <th>{col}</th>
                  <td className="mono">{value ?? <span className="muted">-</span>}</td>
                  <td className="tiny muted">
                    {field && fieldLabel(field)}
                    {cellRef && ` · ${cellRef}`}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </Card>
  );
}
