import { useEffect, useState } from "react";
import { api } from "../api";
import { Card, ErrorBanner, Notice, Spinner, roleWords, useTemplate } from "../components";
import type { BatchDetail, RecordSummary } from "../types";

export default function ExportView({ batch, onRefresh }: { batch: BatchDetail; onRefresh: () => Promise<unknown> }) {
  const [records, setRecords] = useState<RecordSummary[] | null>(null);
  const [historyCount, setHistoryCount] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [downloading, setDownloading] = useState(false);
  const [done, setDone] = useState<string | null>(null);

  useEffect(() => {
    setError(null);
    Promise.all([api.records(batch.id, {}), api.history(batch.id)])
      .then(([r, h]) => {
        setRecords(r);
        setHistoryCount(h.length);
      })
      .catch((e: Error) => setError(e.message));
  }, [batch.id, batch.updated_at]);

  const download = async () => {
    setDownloading(true);
    setError(null);
    setDone(null);
    try {
      const res = await fetch(api.exportUrl(batch.id));
      if (!res.ok) {
        const body = await res.json().catch(() => null);
        throw new Error(body?.detail ?? `Export failed (${res.status}).`);
      }
      const blob = await res.blob();
      const cd = res.headers.get("content-disposition") ?? "";
      const name = /filename="([^"]+)"/.exec(cd)?.[1] ?? `review-${batch.id}.xlsx`;
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = name;
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 2000);
      setDone(name);
      await onRefresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setDownloading(false);
    }
  };

  const c = batch.counts;
  const w = roleWords(useTemplate(batch.template_id));
  const approved = records?.filter((r) => r.review_status === "approved").length ?? 0;
  const exceptions = records?.filter((r) => r.review_status === "awaiting_review").reduce((n, r) => n + r.issue_count, 0) ?? 0;
  const unmatchedRefs =
    records?.filter((r) => r.role === "reference" && r.match_status !== "matched" && r.match_status !== "mismatched").length ?? 0;
  const rejected = batch.files.filter((f) => f.status === "rejected" || f.status === "removed").length;

  return (
    <div className="stack">
      <Card
        title="Review workbook"
        actions={
          <button className="btn btn-primary" onClick={download} disabled={downloading || !records}>
            {downloading ? <Spinner label="Building workbook" /> : "Download XLSX"}
          </button>
        }
      >
        <p className="muted">
          The workbook reflects the current reviewed state, including corrections. Every row carries its source file and page or row reference.
          Amounts are numbers and dates are real dates; text that starts with =, +, - or @ is written as plain text with a leading apostrophe so it is
          never run as a formula.
        </p>
        <ErrorBanner error={error} />
        {done && <Notice tone="good">Downloaded {done}.</Notice>}
        {c.review.awaiting_review > 0 && (
          <Notice tone="warn">
            {w.count(c.review.awaiting_review, w.rec)} {c.review.awaiting_review === 1 ? "is" : "are"} still awaiting review. You can export now; they appear
            as outstanding.
          </Notice>
        )}
        {!c.completeness.complete && c.completeness.gaps.length > 0 && (
          <Notice tone="warn">
            The workbook's Summary sheet will say the inputs are not fully imported and list these files. Their contents are not in the
            export.
          </Notice>
        )}
        {c.needs_mapping > 0 && <Notice tone="warn">{c.needs_mapping} spreadsheet(s) still need a column mapping and are not in the export yet.</Notice>}
        {!records ? (
          <Spinner label="Counting rows" />
        ) : (
          <table className="table compact">
            <thead>
              <tr>
                <th>Sheet</th>
                <th>Contents</th>
                <th className="num">Rows</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td className="strong">Summary</td>
                <td>Batch, template, counts and the scope of the checks</td>
                <td className="num">-</td>
              </tr>
              <tr>
                <td className="strong">All records</td>
                <td>Every {w.rec} and {w.refRow} with current values, statuses and explanations</td>
                <td className="num">{records.length}</td>
              </tr>
              <tr>
                <td className="strong">Approved</td>
                <td>Records a reviewer approved</td>
                <td className="num">{approved}</td>
              </tr>
              <tr>
                <td className="strong">Outstanding exceptions</td>
                <td>One row per open issue on records awaiting review</td>
                <td className="num">{exceptions}</td>
              </tr>
              <tr>
                <td className="strong">Unmatched {w.refRow}s</td>
                <td>{w.RefRow}s without a single paired {w.rec}</td>
                <td className="num">{unmatchedRefs}</td>
              </tr>
              <tr>
                <td className="strong">Rejected files</td>
                <td>Files that could not be processed, or were removed, with reasons</td>
                <td className="num">{rejected}</td>
              </tr>
              <tr>
                <td className="strong">Review history</td>
                <td>Uploads, mappings, corrections, decisions and withdrawals with timestamps</td>
                <td className="num">{historyCount ?? "-"}</td>
              </tr>
            </tbody>
          </table>
        )}
      </Card>
    </div>
  );
}
