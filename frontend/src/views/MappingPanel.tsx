import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { ErrorBanner, Modal, Notice, Spinner } from "../components";
import type { DateAnalysis, FileInfo, Preview, TemplateSummary } from "../types";

const ORDERS = ["DMY", "MDY", "YMD", "UNSPECIFIED"] as const;

export default function MappingPanel({
  file,
  template,
  onClose,
  onConfirmed,
}: {
  file: FileInfo;
  template: TemplateSummary;
  onClose: () => void;
  onConfirmed: () => Promise<unknown>;
}) {
  const [preview, setPreview] = useState<Preview | null>(null);
  const [mapping, setMapping] = useState<Record<string, string | null>>({});
  const [dateOrder, setDateOrder] = useState("DMY");
  const [defaultCurrency, setDefaultCurrency] = useState<string>("");
  const [profileName, setProfileName] = useState("");
  const [analysis, setAnalysis] = useState<DateAnalysis | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(
    async (sheet?: string | null, headerRow?: number | null) => {
      setLoading(true);
      setError(null);
      try {
        const p = await api.preview(file.id, sheet, headerRow);
        setPreview(p);
        setMapping(p.proposed_mapping);
        setDateOrder(p.date_order);
        setDefaultCurrency(p.default_currency ?? "");
        setAnalysis(p.date_analysis);
      } catch (e) {
        setError((e as Error).message);
      } finally {
        setLoading(false);
      }
    },
    [file.id],
  );
  useEffect(() => {
    load();
  }, [load]);

  const dateField = template.fields.find((f) => f.type === "date")?.name;
  const currencyField = template.fields.find((f) => f.type === "currency")?.name;

  const setColumn = async (field: string, column: string | null) => {
    const next = { ...mapping, [field]: column };
    setMapping(next);
    if (field === dateField && preview) {
      if (!column) {
        setAnalysis(null);
        return;
      }
      try {
        const p = await api.preview(file.id, preview.sheet, preview.header_row, column);
        setAnalysis(p.date_analysis);
      } catch {
        setAnalysis(null);
      }
    }
  };

  const problems = useMemo(() => {
    const out: string[] = [];
    const used = new Map<string, string>();
    for (const f of template.fields) {
      const col = mapping[f.name];
      if (col) {
        if (used.has(col)) out.push(`Column "${col}" is mapped to both ${used.get(col)} and ${f.label}.`);
        used.set(col, f.label);
      } else if (f.required && !(f.name === currencyField && defaultCurrency)) {
        out.push(`${f.label} needs a column${f.name === currencyField ? " or a default currency" : ""}.`);
      }
    }
    return out;
  }, [mapping, template.fields, currencyField, defaultCurrency]);

  const confirm = async () => {
    if (!preview) return;
    setSaving(true);
    setError(null);
    try {
      await api.confirmMapping(file.id, {
        sheet: preview.sheet,
        header_row: preview.header_row,
        mapping,
        date_order: dateOrder,
        default_currency: mapping[currencyField ?? ""] ? null : defaultCurrency || null,
        profile_name: profileName.trim() || null,
      });
      await onConfirmed();
    } catch (e) {
      setError((e as Error).message);
      setSaving(false);
    }
  };

  const applyProfile = (id: string) => {
    const p = preview?.profiles.find((x) => String(x.id) === id);
    if (!p || !preview) return;
    const next: Record<string, string | null> = {};
    for (const f of template.fields) {
      const col = p.mapping[f.name];
      next[f.name] = col && preview.headers.includes(col) ? col : null;
    }
    setMapping(next);
    setDateOrder(p.date_order);
    setDefaultCurrency(p.default_currency ?? "");
  };

  const mappedBy = new Map<string, string>();
  for (const f of template.fields) {
    const col = mapping[f.name];
    if (col) mappedBy.set(col, f.label);
  }

  return (
    <Modal
      title={`Map columns: ${file.original_name}`}
      onClose={onClose}
      wide
      footer={
        <>
          <span className="muted small grow">
            {problems.length ? problems[0] : "Ready. The mapping is applied when the batch is processed."}
          </span>
          <button className="btn btn-ghost" onClick={onClose}>
            Cancel
          </button>
          <button className="btn btn-primary" disabled={saving || loading || problems.length > 0} onClick={confirm}>
            {saving ? <Spinner label="Saving" /> : "Confirm mapping"}
          </button>
        </>
      }
    >
      <ErrorBanner error={error} onDismiss={() => setError(null)} />
      {loading && !preview && <Spinner label="Reading the spreadsheet" />}
      {preview && (
        <div className="mapping">
          <div className="mapping-top">
            {preview.sheets.length > 0 && (
              <label className="field inline">
                <span>Worksheet</span>
                <select value={preview.sheet ?? ""} onChange={(e) => load(e.target.value, null)}>
                  {preview.sheets.map((s) => (
                    <option key={s} value={s}>
                      {s}
                    </option>
                  ))}
                </select>
              </label>
            )}
            <label className="field inline">
              <span>Heading row</span>
              <input
                type="number"
                min={1}
                max={1000}
                value={preview.header_row}
                onChange={(e) => {
                  const n = Number(e.target.value);
                  if (n >= 1) load(preview.sheet, n);
                }}
              />
            </label>
            {preview.profiles.length > 0 && (
              <label className="field inline">
                <span>Apply a saved mapping</span>
                <select defaultValue="" onChange={(e) => applyProfile(e.target.value)}>
                  <option value="">Choose...</option>
                  {preview.profiles.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name}
                      {p.id === preview.matching_profile_id ? " (same headings)" : ""}
                    </option>
                  ))}
                </select>
              </label>
            )}
            {loading && <Spinner />}
          </div>
          <Notice>
            Suggestions come from <strong>{preview.proposed_from}</strong>. Headings are matched to configured aliases exactly (ignoring case and
            punctuation); nothing is guessed. Check every row and correct anything that is wrong. {preview.total_rows} data rows found
            {preview.truncated ? " (row limit reached)" : ""}.
          </Notice>

          <div className="grid-2 mapping-grid">
            <div>
              <h3>Fields</h3>
              <table className="table compact">
                <thead>
                  <tr>
                    <th>Field</th>
                    <th>Source column</th>
                  </tr>
                </thead>
                <tbody>
                  {template.fields.map((f) => {
                    const sug = preview.suggestions[f.name];
                    const col = mapping[f.name] ?? "";
                    return (
                      <tr key={f.name}>
                        <td>
                          <span className="strong">{f.label}</span>
                          {f.required && <span className="req">required</span>}
                        </td>
                        <td>
                          <select
                            value={col}
                            onChange={(e) => setColumn(f.name, e.target.value || null)}
                            className={!col && f.required ? "missing" : ""}
                            aria-label={`Column for ${f.label}`}
                          >
                            <option value="">Not in this file</option>
                            {preview.headers.map((h) => (
                              <option key={h} value={h}>
                                {h}
                              </option>
                            ))}
                          </select>
                          {sug?.column && sug.column === col && <div className="muted tiny">Suggested: {sug.reason}</div>}
                          {sug?.column && sug.column !== col && <div className="muted tiny">Alias suggestion was "{sug.column}"</div>}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <div>
              <h3>Assumptions for this file</h3>
              <label className="field">
                <span>Date format</span>
                <select value={dateOrder} onChange={(e) => setDateOrder(e.target.value)}>
                  {ORDERS.map((o) => (
                    <option key={o} value={o}>
                      {preview.date_order_labels[o]}
                    </option>
                  ))}
                </select>
              </label>
              <DateAdvice analysis={analysis} order={dateOrder} labels={preview.date_order_labels} />
              {currencyField && !mapping[currencyField] && (
                <label className="field">
                  <span>Currency for every row (no currency column mapped)</span>
                  <select value={defaultCurrency} onChange={(e) => setDefaultCurrency(e.target.value)}>
                    <option value="">Choose a currency</option>
                    {preview.allowed_currencies.map((c) => (
                      <option key={c} value={c}>
                        {c}
                      </option>
                    ))}
                  </select>
                  <span className="muted tiny">Rows get this currency marked as "Source default", never as extracted.</span>
                </label>
              )}
              <label className="field">
                <span>Save as a reusable mapping (optional)</span>
                <input
                  value={profileName}
                  maxLength={80}
                  placeholder="e.g. Business B purchase register"
                  onChange={(e) => setProfileName(e.target.value)}
                />
                <span className="muted tiny">Files with the same headings will be offered this mapping next time.</span>
              </label>
            </div>
          </div>

          <h3>Preview (first {preview.rows.length} rows)</h3>
          <div className="scroll-x">
            <table className="table compact preview">
              <thead>
                <tr>
                  <th className="muted">Row</th>
                  {preview.headers.map((h) => (
                    <th key={h} className={mappedBy.has(h) ? "mapped" : ""}>
                      {h}
                      {mappedBy.has(h) && <div className="chip">{mappedBy.get(h)}</div>}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {preview.rows.map((r) => (
                  <tr key={r.row}>
                    <td className="muted">{r.row}</td>
                    {r.cells.map((c, i) => (
                      <td key={i} className={mappedBy.has(preview.headers[i]) ? "mapped" : ""}>
                        {c ?? <span className="muted">-</span>}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </Modal>
  );
}

function DateAdvice({ analysis, order, labels }: { analysis: DateAnalysis | null; order: string; labels: Record<string, string> }) {
  if (!analysis) return <div className="muted tiny">Map a date column to see how its values read.</div>;
  if (analysis.values === 0) {
    return analysis.date_cells > 0 ? (
      <div className="muted tiny">All {analysis.date_cells} values are real spreadsheet dates, so the format does not matter.</div>
    ) : (
      <div className="muted tiny">The date column is empty.</div>
    );
  }
  const counts: Record<string, number> = { DMY: analysis.DMY, MDY: analysis.MDY, YMD: analysis.YMD };
  const chosen = order === "UNSPECIFIED" ? analysis.values - analysis.ambiguous_numeric : counts[order];
  const best = (["DMY", "MDY", "YMD"] as const).reduce((a, b) => (counts[b] > counts[a] ? b : a), "DMY" as "DMY" | "MDY" | "YMD");
  const warn = order !== "UNSPECIFIED" && counts[best] > counts[order];
  return (
    <div className={`date-advice ${warn ? "warn" : ""}`}>
      With {labels[order]}: <strong>{chosen}</strong> of {analysis.values} text dates can be read
      {analysis.date_cells > 0 && ` (plus ${analysis.date_cells} real spreadsheet dates)`}.
      {warn && (
        <div>
          {labels[best]} reads {counts[best]} of {analysis.values}. Check which format this file uses before confirming.
        </div>
      )}
      {analysis.ambiguous_numeric > 0 && (
        <div className="muted tiny">
          {analysis.ambiguous_numeric} value{analysis.ambiguous_numeric === 1 ? "" : "s"} would read differently day-first and month-first; the
          format you choose decides them.
        </div>
      )}
    </div>
  );
}
