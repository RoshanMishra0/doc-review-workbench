"""Review workbook export (XLSX).

Exports the current reviewed state, including corrections. Text values that
start with a formula character are prefixed with an apostrophe and written
as plain strings, so they are never evaluated as formulas. Real amounts are
written as numbers and real dates as dates.
"""

from __future__ import annotations

import io
import re
from datetime import date
from decimal import Decimal

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from .db import loads, now_iso
from .labels import labels_for
from .services import _batch_row, _template_for_batch, batch_counts

FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r", "\n")
HEADER_FILL = PatternFill("solid", fgColor="E8EDF3")


def safe_text(value):
    """Neutralise text that a spreadsheet could treat as a formula. Numbers and dates pass through."""
    if isinstance(value, str):
        if value.startswith(FORMULA_PREFIXES):
            return "'" + value
        return value
    return value


def _field_value(field: dict | None):
    """Typed value for export: Decimal for valid money, date for valid dates, text otherwise."""
    if not field:
        return None
    if field.get("error") or field.get("normalized") is None:
        return field.get("current")
    if field["type"] == "money":
        return Decimal(field["normalized"])
    if field["type"] == "date":
        return date.fromisoformat(field["normalized"])
    return field.get("display") or field.get("current")


def _write_sheet(wb: Workbook, title: str, headers: list[str], rows: list[list], formats: dict[int, str] | None = None):
    ws = wb.create_sheet(title)
    ws.append(headers)
    for cell in ws[1]:
        cell.font = Font(bold=True)
        cell.fill = HEADER_FILL
        cell.alignment = Alignment(vertical="top", wrap_text=True)
    for row in rows:
        ws.append([safe_text(v) for v in row])
        r = ws.max_row
        for c_idx, value in enumerate(row, start=1):
            cell = ws.cell(r, c_idx)
            if isinstance(value, str):
                cell.data_type = "s"
            if formats and c_idx in formats and isinstance(value, (Decimal, int, float, date)):
                cell.number_format = formats[c_idx]
    ws.freeze_panes = "A2"
    if rows:
        ws.auto_filter.ref = f"A1:{get_column_letter(len(headers))}{ws.max_row}"
    for idx, head in enumerate(headers, start=1):
        width = max([len(str(head))] + [min(len(str(r[idx - 1])) if r[idx - 1] is not None else 0, 60) for r in rows[:300]])
        ws.column_dimensions[get_column_letter(idx)].width = max(10, min(width + 2, 62))
    return ws


def build_workbook(conn, batch_id: int) -> tuple[bytes, str]:
    batch = _batch_row(conn, batch_id)
    template = _template_for_batch(batch)
    fdefs = template.fields
    labels = labels_for(template)
    ms, vs, rs, cat, fs = (labels["match_status"], labels["validation_status"], labels["review_status"],
                           labels["category"], labels["file_status"])
    inv_plural = template.roles["invoice"].plural
    ref_rows = f"{template.roles['reference'].plural} rows"
    records = conn.execute(
        "SELECT r.*, f.original_name AS file_name FROM records r JOIN files f ON f.id=r.file_id "
        "WHERE r.batch_id=? ORDER BY r.role DESC, r.id", (batch_id,)).fetchall()
    by_id = {r["id"]: r for r in records}
    issues = conn.execute("SELECT * FROM issues WHERE batch_id=? ORDER BY record_id, id", (batch_id,)).fetchall()
    issues_by_record: dict[int, list] = {}
    for i in issues:
        issues_by_record.setdefault(i["record_id"], []).append(i)

    record_headers = ["Record ID", "Role", "Source file", "Source reference"] + [f.label for f in fdefs] + [
        "Corrected fields", "Validation status", "Match status", "Match explanation", "Matched record ID",
        "Matched source reference", "Review status", "Review note or reason", "Reviewed at (UTC)", "Open issues",
        "Extraction method"]
    first_field_col = 5
    formats = {}
    for offset, f in enumerate(fdefs):
        if f.type == "money":
            formats[first_field_col + offset] = "#,##0.00"
        elif f.type == "date":
            formats[first_field_col + offset] = "yyyy-mm-dd"

    def record_row(r) -> list:
        fields = loads(r["fields_json"], {}) or {}
        corrections = loads(r["corrections_json"], {}) or {}
        match = loads(r["match_json"], {}) or {}
        partner = by_id.get(r["partner_id"]) if r["partner_id"] else None
        rec_issues = issues_by_record.get(r["id"], [])
        role_label = template.roles[r["role"]].label
        return [r["id"], role_label, r["file_name"], r["source_ref"]] + [_field_value(fields.get(f.name)) for f in fdefs] + [
            ", ".join(template.label(k) for k in corrections) or None,
            vs.get(r["validation_status"], r["validation_status"]),
            ms.get(r["match_status"], r["match_status"]),
            " ".join(match.get("explanation") or []) or None,
            r["partner_id"],
            partner["source_ref"] if partner else None,
            rs.get(r["review_status"], r["review_status"]),
            r["review_reason"],
            r["reviewed_at"],
            "; ".join(i["message"] for i in rec_issues) or None,
            r["extraction_method"],
        ]

    wb = Workbook()
    summary = wb.active
    summary.title = "Summary"
    counts = batch_counts(conn, batch_id)
    summary_rows = [
        ("Batch", batch["name"]),
        ("Batch ID", batch["id"]),
        ("Template", f"{template.name} (v{batch['template_version']})"),
        ("Exported at (UTC)", now_iso()),
        ("Data", "Synthetic demo data (fictional companies)" if batch["sample_id"] else "Uploaded by the user"),
        ("Inputs fully imported", "Yes" if counts["completeness"]["complete"] else
         "NO - results are incomplete. See 'Files not fully imported' below."),
        (inv_plural, counts["invoices"]),
        (ref_rows, counts["references"]),
        (f"{inv_plural}: approved", counts["review"]["approved"]),
        (f"{inv_plural}: excluded", counts["review"]["excluded"]),
        (f"{inv_plural}: awaiting review", counts["review"]["awaiting_review"]),
        ("Records with open exceptions", counts["open_exception_records"]),
        ("Rejected files", counts["rejected_files"]),
        ("Removed files", counts["files"].get("removed", 0)),
        ("Scope of checks", template.synthetic_note),
    ]
    for gap in counts["completeness"]["gaps"]:
        summary_rows.append((f"Files not fully imported: {gap['file_name']}", f"{gap['status_label']}. {gap['reason']}"))
    for key, value in summary_rows:
        summary.append([key, safe_text(value)])
        summary.cell(summary.max_row, 1).font = Font(bold=True)
    for role, label in (("invoice", inv_plural), ("reference", ref_rows)):
        for status, n in sorted(counts["match"].get(role, {}).items(), key=lambda x: str(x[0])):
            summary.append([f"{label} match status: {ms.get(status, status)}", n])
    summary.column_dimensions["A"].width = 40
    summary.column_dimensions["B"].width = 90

    _write_sheet(wb, "All records", record_headers, [record_row(r) for r in records], formats)
    _write_sheet(wb, "Approved", record_headers,
                 [record_row(r) for r in records if r["review_status"] == "approved"], formats)

    exc_headers = ["Record ID", "Role", "Source reference", "Issue type", "Severity", "Rule", "Field", "Message",
                   "Match status", "Review status"]
    exc_rows = []
    for r in records:
        if r["review_status"] != "awaiting_review":
            continue
        for i in issues_by_record.get(r["id"], []):
            exc_rows.append([
                r["id"], template.roles[r["role"]].label, r["source_ref"],
                cat.get(i["category"], i["category"]), i["severity"], i["rule_id"],
                template.label(i["field"]) if i["field"] in template.field_names else i["field"],
                i["message"], ms.get(r["match_status"], r["match_status"]),
                rs.get(r["review_status"]),
            ])
    _write_sheet(wb, "Outstanding exceptions", exc_headers, exc_rows)

    _write_sheet(wb, f"Unmatched {template.roles['reference'].label.lower()}s"[:31], record_headers,
                 [record_row(r) for r in records
                  if r["role"] == "reference" and r["match_status"] not in ("matched", "mismatched")], formats)

    files = conn.execute("SELECT * FROM files WHERE batch_id=? AND status IN ('rejected','removed') ORDER BY id",
                         (batch_id,)).fetchall()
    _write_sheet(wb, "Rejected files",
                 ["File ID", "File name", "Role", "Type", "Size (bytes)", "Uploaded at (UTC)", "Status", "Reason code",
                  "Reason", "Removed at (UTC)", "SHA-256"],
                 [[f["id"], f["original_name"], template.roles[f["role"]].plural, (f["kind"] or "").upper() or None,
                   f["size_bytes"], f["uploaded_at"], fs.get(f["status"], f["status"]),
                   f["rejection_code"], f["status_detail"], f["removed_at"], f["sha256"]] for f in files])

    history = conn.execute(
        "SELECT h.*, r.source_ref AS record_ref, f.original_name AS file_name FROM history h "
        "LEFT JOIN records r ON r.id=h.record_id LEFT JOIN files f ON f.id=h.file_id "
        "WHERE h.batch_id=? ORDER BY h.id", (batch_id,)).fetchall()
    _write_sheet(wb, "Review history",
                 ["Time (UTC)", "Action", "Actor", "Record ID", "Source reference", "File", "Field", "Old value",
                  "New value", "Note"],
                 [[h["created_at"], h["action"], h["actor"], h["record_id"], h["record_ref"], h["file_name"],
                   template.label(h["field"]) if h["field"] in template.field_names else h["field"],
                   h["old_value"], h["new_value"], h["note"]] for h in history])

    buf = io.BytesIO()
    wb.save(buf)
    safe_name = re.sub(r"-{2,}", "-", "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in batch["name"]))
    safe_name = safe_name.strip("-")[:50] or "batch"
    filename = f"review-{batch['id']}-{safe_name}-{now_iso()[:10]}.xlsx"
    return buf.getvalue(), filename
