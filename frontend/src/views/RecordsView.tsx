import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { Badge, Card, EmptyState, ErrorBanner, Spinner, roleWords, useMeta } from "../components";
import { label, matchTone, reviewTone, validationTone } from "../format";
import { navigate, withQuery } from "../router";
import type { BatchDetail, RecordSummary } from "../types";

export const FILTER_KEYS = ["role", "match_status", "validation_status", "review_status", "category", "q", "corrected"] as const;

export function filtersFrom(query: URLSearchParams): Record<string, string> {
  const out: Record<string, string> = {};
  for (const k of FILTER_KEYS) {
    const v = query.get(k);
    if (v) out[k] = v;
  }
  if (!("role" in out) && !query.has("all")) out.role = "invoice";
  return out;
}

export function filterQuery(filters: Record<string, string>): Record<string, string | undefined> {
  const q: Record<string, string | undefined> = { ...filters };
  if (!filters.role) q.all = "1";
  return q;
}

export default function RecordsView({ batch, query }: { batch: BatchDetail; query: URLSearchParams }) {
  const meta = useMeta();
  const filters = useMemo(() => filtersFrom(query), [query]);
  const [records, setRecords] = useState<RecordSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState(filters.q ?? "");
  const template = meta.templates.find((t) => t.id === batch.template_id)!;
  const labels = template.labels;
  const w = roleWords(template);
  const key = JSON.stringify(filters);

  const load = useCallback(() => {
    setError(null);
    setRecords(null);
    const f = JSON.parse(key) as Record<string, string>;
    api
      .records(batch.id, { ...f, corrected: f.corrected === "1" ? true : undefined })
      .then(setRecords)
      .catch((e: Error) => setError(e.message));
  }, [batch.id, key]);
  useEffect(load, [load, batch.updated_at]);

  const setFilter = (k: string, v: string) => {
    const next = { ...filters, [k]: v };
    if (!v) delete next[k];
    if (k === "role" && !v) delete next.role;
    navigate(withQuery(`/batches/${batch.id}/records`, filterQuery(next)));
  };

  const role = filters.role ?? "";
  const counts = role ? batch.counts.match[role as "invoice" | "reference"] ?? {} : {};
  const statusOptions = role === "reference"
    ? ["matched", "mismatched", "no_invoice", "ambiguous", "invalid", "partner_invalid", "not_compared"]
    : role === "invoice"
      ? ["matched", "mismatched", "missing_from_reference", "ambiguous", "invalid", "not_compared"]
      : Object.keys(labels.match_status);
  const categories = Object.keys(labels.category).filter((c) => c !== "other");
  const total = batch.counts.invoices + batch.counts.references;
  const fieldType = (name: string) => template.fields.find((f) => f.name === name)?.type;
  const isMoney = (name: string) => fieldType(name) === "money";
  const columnClass = (name: string) =>
    ({ money: "num nowrap", date: "nowrap", identifier: "mono" } as Record<string, string>)[fieldType(name) ?? ""] ?? "";
  const reviewHref = (id: number) => withQuery(`#/batches/${batch.id}/records/${id}`, filterQuery(filters));

  return (
    <div className="stack">
      {role && total > 0 && (
        <div className="chips">
          <button className={`chip-btn ${!filters.match_status ? "active" : ""}`} onClick={() => setFilter("match_status", "")}>
            All {role === "invoice" ? `${w.rec}s` : `${w.refRow}s`}{" "}
            <span className="count">{role === "invoice" ? batch.counts.invoices : batch.counts.references}</span>
          </button>
          {statusOptions
            .filter((s) => counts[s])
            .map((s) => (
              <button
                key={s}
                className={`chip-btn tone-${matchTone(s)} ${filters.match_status === s ? "active" : ""}`}
                onClick={() => setFilter("match_status", filters.match_status === s ? "" : s)}
              >
                {label(labels, "match_status", s)} <span className="count">{counts[s]}</span>
              </button>
            ))}
        </div>
      )}
      <Card>
        <div className="filters">
          <label className="field inline">
            <span>Show</span>
            <select value={role} onChange={(e) => setFilter("role", e.target.value)}>
              <option value="invoice">{template.roles.invoice.plural}</option>
              <option value="reference">{template.roles.reference.plural} rows</option>
              <option value="">Everything</option>
            </select>
          </label>
          <label className="field inline">
            <span>Match</span>
            <select value={filters.match_status ?? ""} onChange={(e) => setFilter("match_status", e.target.value)}>
              <option value="">Any</option>
              {statusOptions.map((s) => (
                <option key={s} value={s}>
                  {label(labels, "match_status", s)}
                </option>
              ))}
            </select>
          </label>
          <label className="field inline">
            <span>Checks</span>
            <select value={filters.validation_status ?? ""} onChange={(e) => setFilter("validation_status", e.target.value)}>
              <option value="">Any</option>
              {Object.entries(labels.validation_status).map(([k, v]) => (
                <option key={k} value={k}>
                  {v}
                </option>
              ))}
            </select>
          </label>
          <label className="field inline">
            <span>Issue type</span>
            <select value={filters.category ?? ""} onChange={(e) => setFilter("category", e.target.value)}>
              <option value="">Any</option>
              {categories.map((c) => (
                <option key={c} value={c}>
                  {label(labels, "category", c)}
                </option>
              ))}
            </select>
          </label>
          <label className="field inline">
            <span>Review</span>
            <select value={filters.review_status ?? ""} onChange={(e) => setFilter("review_status", e.target.value)}>
              <option value="">Any</option>
              {Object.entries(labels.review_status).map(([k, v]) => (
                <option key={k} value={k}>
                  {v}
                </option>
              ))}
            </select>
          </label>
          <label className="field inline checkbox">
            <input type="checkbox" checked={filters.corrected === "1"} onChange={(e) => setFilter("corrected", e.target.checked ? "1" : "")} />
            <span>User corrected</span>
          </label>
          <form
            className="search"
            onSubmit={(e) => {
              e.preventDefault();
              setFilter("q", search.trim());
            }}
          >
            <input
              type="search"
              placeholder="Search names, references, files, #id"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              aria-label="Search records"
            />
            <button className="btn btn-small" type="submit">
              Search
            </button>
          </form>
        </div>
        <ErrorBanner error={error} onRetry={load} />
        {!records && !error && <Spinner label="Loading records" />}
        {records && total === 0 && (
          <EmptyState
            title="No records yet"
            actions={
              <a className="btn btn-primary" href={`#/batches/${batch.id}/import`}>
                Go to import
              </a>
            }
          >
            Upload files and press Process on the Import tab. Records appear here once they are extracted.
          </EmptyState>
        )}
        {records && total > 0 && records.length === 0 && (
          <EmptyState title="No records match these filters">
            <button className="link" onClick={() => navigate(`/batches/${batch.id}/records`)}>
              Clear filters
            </button>
          </EmptyState>
        )}
        {records && records.length > 0 && (
          <>
            <div className="muted small table-note">
              {records.length} record{records.length === 1 ? "" : "s"}. Click a row to review it.
            </div>
            <table className="table records">
              <thead>
                <tr>
                  <th className="num">#</th>
                  <th>Source</th>
                  {template.summary_columns.map((c) => (
                    <th key={c.name} className={isMoney(c.name) ? "num" : ""}>
                      {c.label}
                    </th>
                  ))}
                  <th>Checks</th>
                  <th>Match</th>
                  <th>Review</th>
                  <th>Issues</th>
                </tr>
              </thead>
              <tbody>
                {records.map((r) => (
                  <tr key={r.id} className="clickable" onClick={() => (window.location.hash = reviewHref(r.id))}>
                    <td className="num muted">
                      <a href={reviewHref(r.id)} onClick={(e) => e.stopPropagation()}>
                        {r.id}
                      </a>
                    </td>
                    <td className="break small">
                      {r.source_ref}
                      {r.role === "reference" && role === "" && <div className="muted tiny">{template.roles.reference.label}</div>}
                    </td>
                    {template.summary_columns.map((c) => (
                      <td key={c.name} className={columnClass(c.name)}>
                        {cell(r, c.name)}
                      </td>
                    ))}
                    <td>
                      <Badge tone={validationTone(r.validation_status)}>{label(labels, "validation_status", r.validation_status)}</Badge>
                    </td>
                    <td>
                      <Badge tone={matchTone(r.match_status)} title={r.match_summary ?? undefined}>
                        {label(labels, "match_status", r.match_status)}
                      </Badge>
                    </td>
                    <td>
                      <Badge tone={reviewTone(r.review_status)}>{label(labels, "review_status", r.review_status)}</Badge>
                      {r.corrected && (
                        <>
                          {" "}
                          <Badge tone="accent">Corrected</Badge>
                        </>
                      )}
                    </td>
                    <td className="small">
                      {r.categories.length === 0 ? <span className="muted">None</span> : r.categories.map((c) => label(labels, "category", c)).join(", ")}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        )}
      </Card>
    </div>
  );
}

function cell(r: RecordSummary, field: string) {
  const f = r.fields[field];
  if (!f || f.status === "missing") return <span className="value-missing">Missing</span>;
  if (f.error) return <span className="value-invalid" title={f.error}>{f.current}</span>;
  return <>{f.display ?? f.current}</>;
}
