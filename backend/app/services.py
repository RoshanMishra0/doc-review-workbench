"""Application operations on top of SQLite.

Processing outcomes (validation status, match status) are recomputed from
the stored extracted values plus reviewer corrections. Review decisions
(awaiting review / approved / excluded) are stored separately and are only
changed by reviewer actions, or withdrawn when a recompute changes the
outcome a reviewer approved.
"""

from __future__ import annotations

import logging
import shutil
import sqlite3
from collections import Counter
from pathlib import Path

from .db import dumps, loads, log_history, now_iso
from .extraction.base import Evidence, UnreadableDocument
from .extraction.pdf_reader import read_pdf_text
from .extraction.registry import PDF_EXTRACTORS, LayoutRejection, extract_pdf
from .ingestion import (
    IngestionError,
    detect_kind,
    header_signature,
    mapping_problems,
    preview_payload,
    read_table,
    resolve_stored,
    safe_display_name,
    store_upload,
    suggest_mapping,
)
from .matching import STATUS_ISSUES, match_records
from .normalization import DATE_ORDER_LABELS, DATE_ORDERS
from .settings import Settings
from .template_config import ROLES, Template, get_template, load_templates
from .validation import RecordInput, evaluate_batch

log = logging.getLogger(__name__)

REVIEW_STATUSES = ("awaiting_review", "approved", "excluded")
ACTIVE_FILE_STATUSES = ("uploaded", "needs_mapping", "ready", "processed")


class ServiceError(Exception):
    status_code = 400

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class NotFound(ServiceError):
    status_code = 404


class Conflict(ServiceError):
    status_code = 409


# ---------------------------------------------------------------- helpers

def _row(conn: sqlite3.Connection, sql: str, params=()) -> sqlite3.Row | None:
    return conn.execute(sql, params).fetchone()


def _batch_row(conn, batch_id: int) -> sqlite3.Row:
    row = _row(conn, "SELECT * FROM batches WHERE id=?", (batch_id,))
    if row is None:
        raise NotFound(f"Batch {batch_id} was not found.")
    return row


def _file_row(conn, file_id: int) -> sqlite3.Row:
    row = _row(conn, "SELECT * FROM files WHERE id=?", (file_id,))
    if row is None:
        raise NotFound(f"File {file_id} was not found.")
    return row


def _record_row(conn, record_id: int) -> sqlite3.Row:
    row = _row(conn, "SELECT * FROM records WHERE id=?", (record_id,))
    if row is None:
        raise NotFound(f"Record {record_id} was not found.")
    return row


def _touch_batch(conn, batch_id: int) -> None:
    conn.execute("UPDATE batches SET updated_at=? WHERE id=?", (now_iso(), batch_id))


def _template_for_batch(batch: sqlite3.Row) -> Template:
    try:
        return get_template(batch["template_id"])
    except KeyError as exc:
        raise ServiceError(f"Template '{batch['template_id']}' is not installed.") from exc


def _record_label(rec: sqlite3.Row, file_name: str, kind: str) -> str:
    if kind == "pdf":
        return file_name
    return f"{file_name} row {rec['source_row']}"


# ---------------------------------------------------------------- templates

def list_template_summaries() -> list[dict]:
    out = []
    for t in load_templates().values():
        s = t.summary()
        s["pdf_layout_details"] = [
            {"id": i, "name": PDF_EXTRACTORS[i].name, "description": PDF_EXTRACTORS[i].description,
             "date_order": PDF_EXTRACTORS[i].date_order,
             "date_order_label": DATE_ORDER_LABELS[PDF_EXTRACTORS[i].date_order]}
            for i in t.pdf_layouts
        ]
        s["date_order_labels"] = DATE_ORDER_LABELS
        out.append(s)
    return out


def template_summary(template_id: str) -> dict:
    for s in list_template_summaries():
        if s["id"] == template_id:
            return s
    raise NotFound(f"Template '{template_id}' was not found.")


# ---------------------------------------------------------------- batches

def create_batch(conn, name: str, template_id: str, sample_id: str | None = None, actor: str = "reviewer") -> int:
    name = " ".join((name or "").split())[:120]
    if not name:
        raise ServiceError("Give the batch a name.")
    try:
        template = get_template(template_id)
    except KeyError as exc:
        raise ServiceError(f"Template '{template_id}' was not found.") from exc
    ts = now_iso()
    cur = conn.execute(
        "INSERT INTO batches (name, template_id, template_version, sample_id, created_at, updated_at)"
        " VALUES (?,?,?,?,?,?)",
        (name, template.id, template.version, sample_id, ts, ts),
    )
    batch_id = int(cur.lastrowid)
    log_history(conn, batch_id, "batch_created", actor=actor, note=f"Template: {template.name} v{template.version}")
    return batch_id


def batch_counts(conn, batch_id: int) -> dict:
    files = conn.execute("SELECT status FROM files WHERE batch_id=?", (batch_id,)).fetchall()
    file_counts = Counter(r["status"] for r in files)
    recs = conn.execute(
        "SELECT id, role, match_status, validation_status, review_status FROM records WHERE batch_id=?", (batch_id,)
    ).fetchall()
    issue_rows = conn.execute(
        "SELECT i.record_id, i.severity FROM issues i JOIN records r ON r.id=i.record_id "
        "WHERE i.batch_id=? AND r.review_status='awaiting_review'", (batch_id,)
    ).fetchall()
    open_exception_records = {r["record_id"] for r in issue_rows if r["severity"] == "error"}
    invoices = [r for r in recs if r["role"] == "invoice"]
    references = [r for r in recs if r["role"] == "reference"]
    decided = sum(1 for r in invoices if r["review_status"] in ("approved", "excluded"))
    return {
        "files": {"total": len(files), **file_counts},
        "invoices": len(invoices),
        "references": len(references),
        "match": {role: dict(Counter(r["match_status"] for r in recs if r["role"] == role)) for role in ROLES},
        "validation": dict(Counter(r["validation_status"] for r in invoices)),
        "review": {s: sum(1 for r in invoices if r["review_status"] == s) for s in REVIEW_STATUSES},
        "reference_review": {s: sum(1 for r in references if r["review_status"] == s) for s in REVIEW_STATUSES},
        "open_issues": len(issue_rows),
        "open_exception_records": len(open_exception_records),
        "progress": {"decided": decided, "total": len(invoices)},
        "rejected_files": file_counts.get("rejected", 0),
        "needs_mapping": file_counts.get("needs_mapping", 0),
        "pending_files": file_counts.get("uploaded", 0) + file_counts.get("ready", 0),
    }


def list_batches(conn) -> list[dict]:
    rows = conn.execute("SELECT * FROM batches ORDER BY id DESC").fetchall()
    out = []
    for b in rows:
        item = dict(b)
        item["counts"] = batch_counts(conn, b["id"])
        try:
            item["template_name"] = get_template(b["template_id"]).name
        except KeyError:
            item["template_name"] = b["template_id"]
        out.append(item)
    return out


def _file_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    d.pop("stored_name", None)
    d["mapping"] = loads(d.pop("mapping_json"), None)
    return d


def get_batch(conn, batch_id: int) -> dict:
    b = _batch_row(conn, batch_id)
    template = _template_for_batch(b)
    files = conn.execute("SELECT * FROM files WHERE batch_id=? ORDER BY id", (batch_id,)).fetchall()
    return {
        **dict(b),
        "template_name": template.name,
        "files": [_file_dict(f) for f in files],
        "counts": batch_counts(conn, batch_id),
    }


def delete_batch(conn, settings: Settings, batch_id: int) -> None:
    _batch_row(conn, batch_id)
    conn.execute("DELETE FROM batches WHERE id=?", (batch_id,))
    folder = settings.uploads_dir / f"batch_{batch_id}"
    if folder.is_dir() and folder.resolve().is_relative_to(settings.uploads_dir.resolve()):
        shutil.rmtree(folder, ignore_errors=True)


# ---------------------------------------------------------------- files

def add_file(conn, settings: Settings, batch_id: int, role: str, filename: str, data: bytes,
             actor: str = "reviewer") -> dict:
    batch = _batch_row(conn, batch_id)
    template = _template_for_batch(batch)
    if role not in ROLES:
        raise ServiceError(f"Unknown file role '{role}'.")
    name = safe_display_name(filename)
    ts = now_iso()
    kind, reason = detect_kind(name, data[:1024])
    code = None
    if len(data) > settings.max_upload_bytes:
        kind, reason, code = None, (f"The file is larger than the {settings.max_upload_bytes // (1024 * 1024)} MB "
                                    "limit and was not stored."), "too_large"
    elif len(data) == 0:
        reason, code = "The file is empty.", "empty"
    elif kind and kind not in template.roles[role].accepts:
        accepted = ", ".join(k.upper() for k in template.roles[role].accepts)
        reason, code = (f"{template.roles[role].plural} accepts {accepted} files; this is {kind.upper()}.",
                        "wrong_type_for_role")
    elif reason:
        code = "unsupported_type"
    stored, digest = (None, None)
    if code != "too_large":
        stored, digest = store_upload(settings.uploads_dir, batch_id, name, data)
    status = "rejected" if reason else ("needs_mapping" if kind in ("csv", "xlsx") else "uploaded")
    cur = conn.execute(
        "INSERT INTO files (batch_id, role, original_name, stored_name, kind, size_bytes, sha256, status, "
        "status_detail, rejection_code, uploaded_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (batch_id, role, name, stored, kind, len(data), digest, status, reason, code, ts),
    )
    file_id = int(cur.lastrowid)
    if kind in ("csv", "xlsx") and not reason:
        try:
            table = read_table(resolve_stored(settings.uploads_dir, stored), kind, template)
            if not table.headers or not table.rows:
                raise IngestionError("The spreadsheet has no data rows.")
            conn.execute("UPDATE files SET sheet_name=?, header_row=?, date_order=? WHERE id=?",
                         (table.sheet, table.header_row, template.dates.default_order, file_id))
        except IngestionError as exc:
            conn.execute("UPDATE files SET status='rejected', status_detail=?, rejection_code='unreadable' WHERE id=?",
                         (str(exc), file_id))
        except Exception as exc:  # noqa: BLE001 - any reader failure means the file cannot be imported
            log.info("Spreadsheet could not be read (%s)", type(exc).__name__)
            conn.execute("UPDATE files SET status='rejected', status_detail=?, rejection_code='unreadable' WHERE id=?",
                         ("The spreadsheet could not be read. It may be damaged or in an unexpected format.", file_id))
    duplicate = None
    if digest:
        dup = _row(conn, "SELECT id, original_name FROM files WHERE batch_id=? AND sha256=? AND id<>? "
                         "AND status<>'removed' ORDER BY id LIMIT 1", (batch_id, digest, file_id))
        if dup:
            duplicate = dup["original_name"]
    log_history(conn, batch_id, "file_uploaded", actor=actor, file_id=file_id,
                note=f"{name} as {template.roles[role].plural}" + (f"; rejected: {reason}" if reason else "")
                + (f"; same bytes as {duplicate}" if duplicate else ""))
    _touch_batch(conn, batch_id)
    out = _file_dict(_file_row(conn, file_id))
    out["identical_to"] = duplicate
    return out


def stored_path(conn, settings: Settings, file_id: int) -> tuple[Path, sqlite3.Row]:
    f = _file_row(conn, file_id)
    if not f["stored_name"]:
        raise NotFound("This file was not stored (it was rejected before storage).")
    path = resolve_stored(settings.uploads_dir, f["stored_name"])
    if not path.is_file():
        raise NotFound("The stored copy of this file is missing.")
    return path, f


def file_pages(conn, file_id: int) -> list[dict]:
    _file_row(conn, file_id)
    rows = conn.execute("SELECT page_no, text FROM file_pages WHERE file_id=? ORDER BY page_no", (file_id,)).fetchall()
    return [dict(r) for r in rows]


def _profiles_for(conn, template_id: str, role: str) -> list[dict]:
    rows = conn.execute("SELECT * FROM mapping_profiles WHERE template_id=? AND role=? ORDER BY name",
                        (template_id, role)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["mapping"] = loads(d.pop("mapping_json"), {})
        d["headers"] = loads(d.pop("headers_json"), [])
        out.append(d)
    return out


def list_profiles(conn) -> list[dict]:
    rows = conn.execute("SELECT * FROM mapping_profiles ORDER BY name").fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["mapping"] = loads(d.pop("mapping_json"), {})
        d["headers"] = loads(d.pop("headers_json"), [])
        out.append(d)
    return out


def file_preview(conn, settings: Settings, file_id: int, sheet: str | None = None,
                 header_row: int | None = None, date_column: str | None = None) -> dict:
    path, f = stored_path(conn, settings, file_id)
    if f["kind"] not in ("csv", "xlsx"):
        raise ServiceError("Only CSV and XLSX files have a column mapping preview.")
    batch = _batch_row(conn, f["batch_id"])
    template = _template_for_batch(batch)
    use_sheet = sheet if sheet is not None else f["sheet_name"]
    use_header = header_row if header_row is not None else (f["header_row"] if sheet is None else None)
    try:
        table = read_table(path, f["kind"], template, sheet=use_sheet, header_row=use_header)
    except IngestionError as exc:
        raise ServiceError(str(exc)) from exc
    suggestions = suggest_mapping(table.headers, template)
    signature = header_signature(table.headers)
    profiles = _profiles_for(conn, template.id, f["role"])
    matching_profile = next((p for p in profiles if p["header_signature"] == signature), None)
    current = loads(f["mapping_json"], None)
    # Precedence: this file's confirmed mapping, then a saved mapping with identical headings, then aliases.
    if current:
        proposed = {k: v for k, v in current.items()}
        proposed_from = "confirmed mapping"
        date_order, default_currency = f["date_order"], f["default_currency"]
    elif matching_profile:
        proposed = {k: v for k, v in matching_profile["mapping"].items() if v in table.headers}
        proposed_from = f"saved mapping '{matching_profile['name']}'"
        date_order, default_currency = matching_profile["date_order"], matching_profile["default_currency"]
    else:
        proposed = {k: v["column"] for k, v in suggestions.items()}
        proposed_from = "configured aliases"
        date_order, default_currency = template.dates.default_order, None
    analysis_mapping = dict(proposed)
    if date_column is not None:
        for fd in template.fields:
            if fd.type == "date":
                analysis_mapping[fd.name] = date_column or None
    payload = preview_payload(table, template, analysis_mapping)
    payload.update({
        "file": _file_dict(f),
        "suggestions": suggestions,
        "proposed_mapping": proposed,
        "proposed_from": proposed_from,
        "profiles": profiles,
        "matching_profile_id": matching_profile["id"] if matching_profile else None,
        "date_order": date_order or template.dates.default_order,
        "default_currency": default_currency,
        "date_order_labels": DATE_ORDER_LABELS,
        "fields": [fd.model_dump() for fd in template.fields],
        "allowed_currencies": template.currency.allowed,
    })
    return payload


def confirm_mapping(conn, settings: Settings, file_id: int, *, sheet: str | None, header_row: int | None,
                    mapping: dict[str, str | None], date_order: str, default_currency: str | None,
                    profile_name: str | None = None, actor: str = "reviewer", note: str | None = None) -> dict:
    path, f = stored_path(conn, settings, file_id)
    if f["status"] not in ("needs_mapping", "ready"):
        raise Conflict("The mapping can only be changed before the file is processed. "
                       "Remove the file and upload it again to import it differently.")
    batch = _batch_row(conn, f["batch_id"])
    template = _template_for_batch(batch)
    if date_order not in DATE_ORDERS:
        raise ServiceError(f"Unknown date format '{date_order}'.")
    default_currency = (default_currency or "").strip().upper() or None
    table = read_table(path, f["kind"], template, sheet=sheet, header_row=header_row)
    clean = {k: (v or None) for k, v in mapping.items()}
    for fd in template.fields:
        clean.setdefault(fd.name, None)
    if clean.get(template.currency_field):
        default_currency = None  # a mapped currency column wins; no silent default
    problems = mapping_problems(clean, table.headers, template, default_currency)
    if problems:
        raise ServiceError(" ".join(problems))
    profile_id = None
    if profile_name and profile_name.strip():
        pname = " ".join(profile_name.split())[:80]
        ts = now_iso()
        existing = _row(conn, "SELECT id FROM mapping_profiles WHERE name=?", (pname,))
        values = (template.id, f["role"], header_signature(table.headers), dumps(table.headers), dumps(clean),
                  date_order, default_currency, ts)
        if existing:
            conn.execute("UPDATE mapping_profiles SET template_id=?, role=?, header_signature=?, headers_json=?, "
                         "mapping_json=?, date_order=?, default_currency=?, updated_at=? WHERE id=?",
                         (*values, existing["id"]))
            profile_id = existing["id"]
        else:
            cur = conn.execute("INSERT INTO mapping_profiles (template_id, role, header_signature, headers_json, "
                               "mapping_json, date_order, default_currency, updated_at, name, created_at) "
                               "VALUES (?,?,?,?,?,?,?,?,?,?)", (*values, pname, ts))
            profile_id = int(cur.lastrowid)
    conn.execute("UPDATE files SET status='ready', sheet_name=?, header_row=?, mapping_json=?, date_order=?, "
                 "default_currency=?, mapping_profile_id=?, status_detail=? WHERE id=?",
                 (table.sheet, table.header_row, dumps(clean), date_order, default_currency, profile_id,
                  f"Mapping confirmed: {len(table.rows)} data rows, dates read as {DATE_ORDER_LABELS[date_order]}"
                  + (f", default currency {default_currency}" if default_currency else ""), file_id))
    described = "; ".join(f"{template.label(k)} <- {v}" for k, v in clean.items() if v)
    log_history(conn, f["batch_id"], "mapping_confirmed", actor=actor, file_id=file_id, new_value=described,
                note=(note or "") + (f" Saved as mapping '{profile_name}'." if profile_id else ""))
    _touch_batch(conn, f["batch_id"])
    return _file_dict(_file_row(conn, file_id))


def remove_file(conn, file_id: int, actor: str = "reviewer") -> None:
    f = _file_row(conn, file_id)
    if f["status"] == "removed":
        return
    conn.execute("DELETE FROM records WHERE file_id=?", (file_id,))
    conn.execute("UPDATE files SET status='removed', record_count=0, "
                 "status_detail='Removed by a reviewer; its records were deleted.' WHERE id=?", (file_id,))
    log_history(conn, f["batch_id"], "file_removed", actor=actor, file_id=file_id, note=f["original_name"])
    recompute_batch(conn, f["batch_id"], actor="system", reason=f"file {f['original_name']} removed")


# ---------------------------------------------------------------- processing

def _reject(conn, file_id: int, code: str, reason: str, page_count: int | None = None) -> None:
    conn.execute("UPDATE files SET status='rejected', rejection_code=?, status_detail=?, page_count=?, "
                 "processed_at=? WHERE id=?", (code, reason, page_count, now_iso(), file_id))


def _insert_record(conn, batch_id: int, f: sqlite3.Row, *, source_ref: str, method: str, date_order: str,
                   extracted: dict, page: int | None = None, row: int | None = None, cells: dict | None = None,
                   notes: list[str] | None = None) -> int:
    ts = now_iso()
    cur = conn.execute(
        "INSERT INTO records (batch_id, file_id, role, source_ref, source_page, source_row, extraction_method, "
        "date_order, extracted_json, source_cells_json, notes_json, created_at, updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (batch_id, f["id"], f["role"], source_ref, page, row, method, date_order, dumps(extracted),
         dumps(cells) if cells is not None else None, dumps(notes or []), ts, ts),
    )
    return int(cur.lastrowid)


def _process_pdf(conn, settings: Settings, f: sqlite3.Row, template: Template) -> None:
    path = resolve_stored(settings.uploads_dir, f["stored_name"])
    try:
        doc = read_pdf_text(path)
    except UnreadableDocument as exc:
        _reject(conn, f["id"], exc.code, exc.reason)
        return
    conn.execute("DELETE FROM file_pages WHERE file_id=?", (f["id"],))
    for i, text in enumerate(doc.pages, start=1):
        conn.execute("INSERT INTO file_pages (file_id, page_no, text) VALUES (?,?,?)", (f["id"], i, text))
    result = extract_pdf(doc, template.pdf_layouts)
    if isinstance(result, LayoutRejection):
        _reject(conn, f["id"], result.code, result.reason, len(doc.pages))
        return
    extracted = {name: ef.to_dict() for name, ef in result.fields.items() if name in template.field_names}
    for fd in template.fields:
        extracted.setdefault(fd.name, {"value": None, "kind": "text", "evidence": None})
    missing = [template.label(n) for n, v in extracted.items() if v["value"] is None]
    page = result.source_page or 1
    _insert_record(conn, f["batch_id"], f, source_ref=f"{f['original_name']}, page {page}", method=result.method,
                   date_order=result.date_order, extracted=extracted, page=page, notes=result.notes)
    detail = f"{PDF_EXTRACTORS[result.layout_id].name} layout; {len(extracted) - len(missing)} of {len(extracted)} fields found"
    if missing:
        detail += f" (not found: {', '.join(missing)})"
    conn.execute("UPDATE files SET status='processed', layout_id=?, page_count=?, record_count=1, status_detail=?, "
                 "processed_at=? WHERE id=?", (result.layout_id, len(doc.pages), detail, now_iso(), f["id"]))


def _process_sheet(conn, settings: Settings, f: sqlite3.Row, template: Template) -> None:
    path = resolve_stored(settings.uploads_dir, f["stored_name"])
    mapping: dict[str, str | None] = loads(f["mapping_json"], {})
    try:
        table = read_table(path, f["kind"], template, sheet=f["sheet_name"], header_row=f["header_row"])
    except IngestionError as exc:
        _reject(conn, f["id"], "unreadable", str(exc))
        return
    index = {h: i for i, h in enumerate(table.headers)}
    missing_cols = [c for c in mapping.values() if c and c not in index]
    if missing_cols:
        _reject(conn, f["id"], "mapping_mismatch", f"Mapped columns not found: {', '.join(missing_cols)}.")
        return
    currency_field = template.currency_field
    where = f"sheet '{table.sheet}', " if table.sheet else ""
    method = "Spreadsheet import with confirmed column mapping"
    count = 0
    for row_no, cells in table.rows:
        extracted: dict[str, dict] = {}
        notes: list[str] = []
        for fd in template.fields:
            col = mapping.get(fd.name)
            if col:
                cell = cells[index[col]]
                ev = Evidence(cell=cell.coord or None, column=col, text=cell.text)
                extracted[fd.name] = {"value": cell.text, "kind": cell.kind, "evidence": ev.to_dict()}
                if fd.type == "identifier" and cell.kind == "number":
                    notes.append(f"{fd.label} was read from a numeric cell ({cell.text}); any leading zeros "
                                 "were already lost in the spreadsheet and cannot be recovered.")
            elif fd.name == currency_field and f["default_currency"]:
                extracted[fd.name] = {"value": f["default_currency"], "kind": "source_default",
                                      "evidence": {"text": f"Default currency chosen at import: {f['default_currency']}"}}
            else:
                extracted[fd.name] = {"value": None, "kind": "text", "evidence": None}
        cell_map = {h: cells[i].text for h, i in index.items()}
        _insert_record(conn, f["batch_id"], f, source_ref=f"{f['original_name']}, {where}row {row_no}",
                       method=method, date_order=f["date_order"] or template.dates.default_order,
                       extracted=extracted, row=row_no, cells=cell_map, notes=notes)
        count += 1
    detail = f"{count} rows imported" + (f" from sheet '{table.sheet}'" if table.sheet else "")
    if table.truncated:
        detail += " (row limit reached; later rows were not imported)"
    conn.execute("UPDATE files SET status='processed', record_count=?, status_detail=?, processed_at=? WHERE id=?",
                 (count, detail, now_iso(), f["id"]))


def process_batch(conn, settings: Settings, batch_id: int, actor: str = "reviewer") -> dict:
    batch = _batch_row(conn, batch_id)
    template = _template_for_batch(batch)
    pending = conn.execute("SELECT * FROM files WHERE batch_id=? AND status IN ('uploaded','ready') ORDER BY id",
                           (batch_id,)).fetchall()
    for f in pending:
        if f["kind"] == "pdf":
            _process_pdf(conn, settings, f, template)
        else:
            _process_sheet(conn, settings, f, template)
    summary = recompute_batch(conn, batch_id, actor="system", reason="batch processed")
    conn.execute("UPDATE batches SET last_processed_at=? WHERE id=?", (now_iso(), batch_id))
    waiting = conn.execute("SELECT original_name FROM files WHERE batch_id=? AND status='needs_mapping'",
                           (batch_id,)).fetchall()
    log_history(conn, batch_id, "batch_processed", actor=actor,
                note=f"{len(pending)} file(s) processed" + (f"; {len(waiting)} waiting for column mapping" if waiting else ""))
    summary["processed_files"] = len(pending)
    summary["waiting_for_mapping"] = [w["original_name"] for w in waiting]
    return summary


def _build_inputs(conn, batch_id: int) -> tuple[list[RecordInput], dict[int, sqlite3.Row]]:
    rows = conn.execute(
        "SELECT r.*, f.original_name AS file_name, f.kind AS file_kind FROM records r JOIN files f ON f.id=r.file_id "
        "WHERE r.batch_id=? ORDER BY r.id", (batch_id,)).fetchall()
    inputs = []
    for r in rows:
        extracted = loads(r["extracted_json"], {})
        corrections = loads(r["corrections_json"], {})
        original = {k: v.get("value") for k, v in extracted.items()}
        kinds = {k: v.get("kind", "text") for k, v in extracted.items()}
        values = {**original, **corrections}
        inputs.append(RecordInput(
            id=r["id"], role=r["role"], values=values, original=original, kinds=kinds,
            corrected=set(corrections), date_order=r["date_order"], excluded=r["review_status"] == "excluded",
            label=_record_label(r, r["file_name"], r["file_kind"]), notes=loads(r["notes_json"], []),
        ))
    return inputs, {r["id"]: r for r in rows}


def _issue_signature(conn, record_id: int) -> tuple:
    rows = conn.execute("SELECT category, field, rule_id FROM issues WHERE record_id=? ORDER BY category, field, rule_id",
                        (record_id,)).fetchall()
    return tuple((r["category"], r["field"], r["rule_id"]) for r in rows)


def recompute_batch(conn, batch_id: int, *, actor: str, reason: str, changed_record_ids: set[int] | None = None) -> dict:
    """Re-run normalization, validation and matching for the whole batch.

    Approved records whose outcome changes are moved back to awaiting review,
    and the reason is written to the history.
    """
    batch = _batch_row(conn, batch_id)
    template = _template_for_batch(batch)
    changed_record_ids = changed_record_ids or set()
    inputs, rows = _build_inputs(conn, batch_id)
    before = {rid: (r["match_status"], r["partner_id"], r["validation_status"], _issue_signature(conn, rid))
              for rid, r in rows.items()}
    evaluated = evaluate_batch(inputs, template)
    links = {r["record_id"]: r["reference_id"] for r in conn.execute(
        "SELECT ml.record_id, ml.reference_id FROM manual_links ml JOIN records r ON r.id=ml.record_id "
        "WHERE r.batch_id=?", (batch_id,)).fetchall()}
    results, dropped = match_records(evaluated, template, links)
    for inv_id, ref_id, why in dropped:
        conn.execute("DELETE FROM manual_links WHERE record_id=?", (inv_id,))
        if inv_id in rows:
            log_history(conn, batch_id, "link_removed", actor="system", record_id=inv_id,
                        new_value=f"record #{ref_id}", note=why)
    conn.execute("DELETE FROM issues WHERE batch_id=?", (batch_id,))
    ts = now_iso()
    for ev in evaluated:
        result = results[ev.id]
        conn.execute(
            "UPDATE records SET fields_json=?, checks_json=?, validation_status=?, match_status=?, match_json=?, "
            "partner_id=? WHERE id=?",
            (dumps({k: v.to_dict() for k, v in ev.fields.items()}), dumps([c.to_dict() for c in ev.checks]),
             ev.validation_status, result.status, dumps(result.to_dict()), result.partner_id, ev.id))
        for c in ev.issues:
            conn.execute("INSERT INTO issues (batch_id, record_id, kind, category, rule_id, field, severity, message) "
                         "VALUES (?,?,?,?,?,?,?,?)",
                         (batch_id, ev.id, "validation", c.category or "other", c.rule_id, c.field, c.severity, c.message))
        issue = STATUS_ISSUES.get(result.status)
        if issue is None and result.status == "not_compared" and result.no_reference_rows:
            issue = ("not_compared", "warning")
        if issue:
            conn.execute("INSERT INTO issues (batch_id, record_id, kind, category, rule_id, field, severity, message) "
                         "VALUES (?,?,?,?,?,?,?,?)",
                         (batch_id, ev.id, "matching", issue[0], "matching", None, issue[1],
                          " ".join(result.explanation)))
    withdrawn = []
    for ev in evaluated:
        row = rows[ev.id]
        if row["review_status"] != "approved":
            continue
        result = results[ev.id]
        after = (result.status, result.partner_id, ev.validation_status, _issue_signature(conn, ev.id))
        if ev.id in changed_record_ids or after != before[ev.id]:
            why = ("its values were corrected" if ev.id in changed_record_ids
                   else f"its checks or matching result changed ({reason})")
            conn.execute("UPDATE records SET review_status='awaiting_review', review_reason=NULL, reviewed_at=NULL, "
                         "updated_at=? WHERE id=?", (ts, ev.id))
            log_history(conn, batch_id, "approval_withdrawn", actor="system", record_id=ev.id,
                        old_value="approved", new_value="awaiting_review", note=f"Approval withdrawn because {why}.")
            withdrawn.append(ev.id)
    _touch_batch(conn, batch_id)
    counts = batch_counts(conn, batch_id)
    counts["approvals_withdrawn"] = withdrawn
    return counts


# ---------------------------------------------------------------- records

def _summary_row(r: sqlite3.Row, issues: list[sqlite3.Row]) -> dict:
    fields = loads(r["fields_json"], {}) or {}

    def disp(name):
        f = fields.get(name) or {}
        return f.get("display") or f.get("current")

    match = loads(r["match_json"], {}) or {}
    return {
        "id": r["id"],
        "role": r["role"],
        "file_id": r["file_id"],
        "file_name": r["file_name"],
        "source_ref": r["source_ref"],
        "supplier_name": disp("supplier_name"),
        "invoice_number": disp("invoice_number"),
        "invoice_date": disp("invoice_date"),
        "currency": disp("currency"),
        "total_amount": disp("total_amount"),
        "fields": {k: {"display": v.get("display"), "current": v.get("current"), "status": v.get("status"),
                       "error": v.get("error")} for k, v in fields.items()},
        "validation_status": r["validation_status"],
        "match_status": r["match_status"],
        "match_summary": (match.get("explanation") or [None])[0],
        "partner_id": r["partner_id"],
        "review_status": r["review_status"],
        "corrected": bool(loads(r["corrections_json"], {})),
        "issue_count": len(issues),
        "error_count": sum(1 for i in issues if i["severity"] == "error"),
        "categories": sorted({i["category"] for i in issues}),
        "updated_at": r["updated_at"],
    }


def list_records(conn, batch_id: int, *, role: str | None = None, match_status: str | None = None,
                 validation_status: str | None = None, review_status: str | None = None,
                 category: str | None = None, q: str | None = None, corrected: bool | None = None) -> list[dict]:
    _batch_row(conn, batch_id)
    sql = ("SELECT r.*, f.original_name AS file_name FROM records r JOIN files f ON f.id=r.file_id "
           "WHERE r.batch_id=?")
    params: list = [batch_id]
    for col, val in (("r.role", role), ("r.match_status", match_status),
                     ("r.validation_status", validation_status), ("r.review_status", review_status)):
        if val:
            sql += f" AND {col}=?"
            params.append(val)
    sql += " ORDER BY r.role DESC, r.id"
    rows = conn.execute(sql, params).fetchall()
    issues_by_record: dict[int, list] = {}
    for i in conn.execute("SELECT * FROM issues WHERE batch_id=?", (batch_id,)).fetchall():
        issues_by_record.setdefault(i["record_id"], []).append(i)
    out = []
    needle = (q or "").strip().casefold()
    for r in rows:
        item = _summary_row(r, issues_by_record.get(r["id"], []))
        if category and category not in item["categories"]:
            continue
        if corrected is not None and item["corrected"] != corrected:
            continue
        if needle:
            values = [f.get("display") or f.get("current") for f in item["fields"].values()]
            hay = " ".join(str(x) for x in (*values, item["file_name"], item["source_ref"], f"#{item['id']}")
                           if x).casefold()
            if needle not in hay:
                continue
        out.append(item)
    return out


def _brief(conn, record_id: int | None) -> dict | None:
    if not record_id:
        return None
    r = _row(conn, "SELECT r.*, f.original_name AS file_name FROM records r JOIN files f ON f.id=r.file_id "
                   "WHERE r.id=?", (record_id,))
    if r is None:
        return None
    issues = conn.execute("SELECT * FROM issues WHERE record_id=?", (record_id,)).fetchall()
    return _summary_row(r, issues)


def record_detail(conn, record_id: int) -> dict:
    r = _row(conn, "SELECT r.*, f.original_name AS file_name, f.kind AS file_kind, f.layout_id, f.sheet_name "
                   "FROM records r JOIN files f ON f.id=r.file_id WHERE r.id=?", (record_id,))
    if r is None:
        raise NotFound(f"Record {record_id} was not found.")
    batch = _batch_row(conn, r["batch_id"])
    template = _template_for_batch(batch)
    issues = conn.execute("SELECT * FROM issues WHERE record_id=? ORDER BY kind DESC, severity, id",
                          (record_id,)).fetchall()
    match = loads(r["match_json"], {}) or {}
    history = conn.execute("SELECT * FROM history WHERE record_id=? ORDER BY id", (record_id,)).fetchall()
    link = _row(conn, "SELECT * FROM manual_links WHERE record_id=? OR reference_id=?", (record_id, record_id))
    extracted = loads(r["extracted_json"], {})
    pages = []
    if r["file_kind"] == "pdf":
        pages = [dict(p) for p in conn.execute("SELECT page_no, text FROM file_pages WHERE file_id=? ORDER BY page_no",
                                               (r["file_id"],)).fetchall()]
    detail = _summary_row(r, issues)
    detail.update({
        "batch_id": r["batch_id"],
        "template_id": batch["template_id"],
        "file_kind": r["file_kind"],
        "layout_id": r["layout_id"],
        "extraction_method": r["extraction_method"],
        "date_order": r["date_order"],
        "date_order_label": DATE_ORDER_LABELS.get(r["date_order"], r["date_order"]),
        "field_defs": [fd.model_dump() for fd in template.fields],
        "fields": loads(r["fields_json"], {}),
        "extracted": extracted,
        "corrections": loads(r["corrections_json"], {}),
        "checks": loads(r["checks_json"], []),
        "issues": [dict(i) for i in issues],
        "match": match,
        "partner": _brief(conn, r["partner_id"]),
        "candidates": [c for c in (_brief(conn, cid) for cid in match.get("candidates", [])) if c],
        "manual_link": dict(link) if link else None,
        "source_cells": loads(r["source_cells_json"], None),
        "pages": pages,
        "notes": loads(r["notes_json"], []),
        "review_reason": r["review_reason"],
        "reviewed_at": r["reviewed_at"],
        "history": [dict(h) for h in history],
        "role_label": template.roles[r["role"]].label,
    })
    return detail


def _require_reviewable(r: sqlite3.Row, *allowed: str) -> None:
    if r["review_status"] not in allowed:
        nice = r["review_status"].replace("_", " ")
        raise Conflict(f"This record is {nice}. Reopen it first.")


def correct_record(conn, record_id: int, values: dict[str, str | None], note: str | None = None,
                   actor: str = "reviewer") -> dict:
    r = _record_row(conn, record_id)
    batch = _batch_row(conn, r["batch_id"])
    template = _template_for_batch(batch)
    if not values:
        raise ServiceError("No corrections were given.")
    extracted = loads(r["extracted_json"], {})
    corrections: dict[str, str] = loads(r["corrections_json"], {})
    changed = []
    for name, new in values.items():
        if name not in template.field_names:
            raise ServiceError(f"Unknown field '{name}'.")
        original = (extracted.get(name) or {}).get("value")
        current = corrections.get(name, original)
        new_clean = None if new is None else " ".join(str(new).split())
        if new_clean == "":
            new_clean = None
        if new is None or new_clean == original:
            # Revert to the extracted value.
            if name in corrections:
                corrections.pop(name)
                changed.append(name)
                log_history(conn, r["batch_id"], "correction_reverted", actor=actor, record_id=record_id, field=name,
                            old_value=current, new_value=original, note=note)
            continue
        if new_clean == current:
            continue
        corrections[name] = new_clean
        changed.append(name)
        log_history(conn, r["batch_id"], "corrected", actor=actor, record_id=record_id, field=name,
                    old_value=current, new_value=new_clean, note=note)
    if not changed:
        raise ServiceError("Nothing changed: the values are the same as the current ones.")
    conn.execute("UPDATE records SET corrections_json=?, updated_at=? WHERE id=?",
                 (dumps(corrections), now_iso(), record_id))
    summary = recompute_batch(conn, r["batch_id"], actor="system", reason=f"record #{record_id} corrected",
                              changed_record_ids={record_id})
    return {"record": record_detail(conn, record_id), "summary": summary, "changed_fields": changed}


def approve_record(conn, record_id: int, note: str | None = None, actor: str = "reviewer") -> dict:
    r = _record_row(conn, record_id)
    _require_reviewable(r, "awaiting_review")
    errors = conn.execute("SELECT COUNT(*) FROM issues WHERE record_id=? AND severity='error'", (record_id,)).fetchone()[0]
    note = (note or "").strip() or None
    if errors and not note:
        raise ServiceError(f"This record has {errors} open issue(s). Add a note explaining why it is approved anyway, "
                           "or correct it first.")
    ts = now_iso()
    conn.execute("UPDATE records SET review_status='approved', review_reason=?, reviewed_at=?, updated_at=? WHERE id=?",
                 (note, ts, ts, record_id))
    log_history(conn, r["batch_id"], "approved", actor=actor, record_id=record_id, old_value=r["review_status"],
                new_value="approved", note=note if not errors else f"Approved with {errors} open issue(s): {note}")
    _touch_batch(conn, r["batch_id"])
    return record_detail(conn, record_id)


def exclude_record(conn, record_id: int, reason: str, actor: str = "reviewer") -> dict:
    r = _record_row(conn, record_id)
    _require_reviewable(r, "awaiting_review", "approved")
    reason = (reason or "").strip()
    if not reason:
        raise ServiceError("Give a reason for excluding this record.")
    ts = now_iso()
    conn.execute("DELETE FROM manual_links WHERE record_id=? OR reference_id=?", (record_id, record_id))
    conn.execute("UPDATE records SET review_status='excluded', review_reason=?, reviewed_at=?, updated_at=? WHERE id=?",
                 (reason, ts, ts, record_id))
    log_history(conn, r["batch_id"], "excluded", actor=actor, record_id=record_id, old_value=r["review_status"],
                new_value="excluded", note=reason)
    recompute_batch(conn, r["batch_id"], actor="system", reason=f"record #{record_id} excluded")
    return record_detail(conn, record_id)


def reopen_record(conn, record_id: int, note: str | None = None, actor: str = "reviewer") -> dict:
    r = _record_row(conn, record_id)
    _require_reviewable(r, "approved", "excluded")
    conn.execute("UPDATE records SET review_status='awaiting_review', review_reason=NULL, reviewed_at=NULL, "
                 "updated_at=? WHERE id=?", (now_iso(), record_id))
    log_history(conn, r["batch_id"], "reopened", actor=actor, record_id=record_id, old_value=r["review_status"],
                new_value="awaiting_review", note=(note or "").strip() or None)
    if r["review_status"] == "excluded":
        recompute_batch(conn, r["batch_id"], actor="system", reason=f"record #{record_id} reopened")
    return record_detail(conn, record_id)


def add_note(conn, record_id: int, note: str, actor: str = "reviewer") -> dict:
    r = _record_row(conn, record_id)
    note = (note or "").strip()
    if not note:
        raise ServiceError("The note is empty.")
    log_history(conn, r["batch_id"], "note", actor=actor, record_id=record_id, note=note[:2000])
    conn.execute("UPDATE records SET updated_at=? WHERE id=?", (now_iso(), record_id))
    return record_detail(conn, record_id)


def link_record(conn, record_id: int, reference_id: int, note: str | None = None, actor: str = "reviewer") -> dict:
    r = _record_row(conn, record_id)
    ref = _record_row(conn, reference_id)
    if r["role"] == "reference" and ref["role"] == "invoice":
        r, ref = ref, r
        record_id, reference_id = r["id"], ref["id"]
    if r["role"] != "invoice" or ref["role"] != "reference" or r["batch_id"] != ref["batch_id"]:
        raise ServiceError("Link an invoice to a register row from the same batch.")
    if r["match_status"] != "ambiguous":
        raise Conflict("Only records with an ambiguous match can be linked manually.")
    match = loads(r["match_json"], {}) or {}
    if reference_id not in (match.get("candidates") or []):
        raise ServiceError("That register row is not one of this record's candidates (same identity).")
    if _row(conn, "SELECT 1 FROM manual_links WHERE reference_id=?", (reference_id,)):
        raise Conflict("That register row is already linked to another invoice.")
    conn.execute("INSERT OR REPLACE INTO manual_links (record_id, reference_id, created_at) VALUES (?,?,?)",
                 (record_id, reference_id, now_iso()))
    log_history(conn, r["batch_id"], "linked", actor=actor, record_id=record_id, new_value=f"record #{reference_id}",
                note=(note or "").strip() or None)
    log_history(conn, r["batch_id"], "linked", actor=actor, record_id=reference_id, new_value=f"record #{record_id}",
                note=(note or "").strip() or None)
    recompute_batch(conn, r["batch_id"], actor="system", reason=f"record #{record_id} linked to #{reference_id}")
    return record_detail(conn, record_id)


def unlink_record(conn, record_id: int, actor: str = "reviewer") -> dict:
    r = _record_row(conn, record_id)
    link = _row(conn, "SELECT * FROM manual_links WHERE record_id=? OR reference_id=?", (record_id, record_id))
    if not link:
        raise Conflict("This record has no manual link.")
    conn.execute("DELETE FROM manual_links WHERE record_id=?", (link["record_id"],))
    for rid, other in ((link["record_id"], link["reference_id"]), (link["reference_id"], link["record_id"])):
        log_history(conn, r["batch_id"], "unlinked", actor=actor, record_id=rid, old_value=f"record #{other}")
    recompute_batch(conn, r["batch_id"], actor="system", reason=f"manual link of record #{record_id} removed")
    return record_detail(conn, record_id)


def batch_history(conn, batch_id: int) -> list[dict]:
    _batch_row(conn, batch_id)
    rows = conn.execute(
        "SELECT h.*, r.source_ref AS record_ref, f.original_name AS file_name FROM history h "
        "LEFT JOIN records r ON r.id=h.record_id LEFT JOIN files f ON f.id=h.file_id "
        "WHERE h.batch_id=? ORDER BY h.id", (batch_id,)).fetchall()
    return [dict(r) for r in rows]
