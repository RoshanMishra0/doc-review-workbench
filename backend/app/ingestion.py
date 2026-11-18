"""File intake: type checks, storage under generated names, spreadsheet reading and mapping suggestions."""

from __future__ import annotations

import csv
import hashlib
import io
import re
import uuid
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path

from openpyxl import load_workbook

from .normalization import analyse_date_column, normalize_header
from .template_config import Template

ALLOWED_EXTENSIONS = {".pdf": "pdf", ".csv": "csv", ".xlsx": "xlsx"}
MAX_PREVIEW_ROWS = 12
MAX_SPREADSHEET_ROWS = 20000
HEADER_SCAN_ROWS = 20


class IngestionError(Exception):
    """A user-facing problem with an uploaded file."""


def safe_display_name(name: str) -> str:
    """Strip directories and control characters from a client-supplied file name."""
    base = re.split(r"[\\/]", name or "")[-1]
    base = "".join(ch for ch in base if ch.isprintable()).strip()
    return (base or "unnamed")[:200]


def detect_kind(filename: str, head: bytes) -> tuple[str | None, str | None]:
    """Return (kind, rejection_reason)."""
    ext = Path(filename).suffix.lower()
    if ext == ".xls":
        return None, "Legacy .xls workbooks are not supported. Save the file as .xlsx or CSV and upload it again."
    kind = ALLOWED_EXTENSIONS.get(ext)
    if kind is None:
        return None, f"Files of type '{ext or 'no extension'}' are not supported. Upload PDF, CSV or XLSX files."
    if kind == "pdf" and b"%PDF-" not in head[:1024]:
        # Keep it: the PDF reader reports a clear reason during processing.
        return "pdf", None
    if kind == "xlsx" and not head.startswith(b"PK"):
        return None, "The file has an .xlsx extension but is not an XLSX workbook."
    return kind, None


def store_upload(uploads_dir: Path, batch_id: int, filename: str, data: bytes) -> tuple[str, str]:
    """Write bytes under a generated name. Returns (stored_relative_name, sha256)."""
    folder = uploads_dir / f"batch_{batch_id}"
    folder.mkdir(parents=True, exist_ok=True)
    ext = Path(filename).suffix.lower()
    ext = ext if ext in ALLOWED_EXTENSIONS or ext == ".xls" else ".bin"
    stored = f"batch_{batch_id}/{uuid.uuid4().hex}{ext}"
    target = uploads_dir / stored
    with target.open("xb") as fh:  # never overwrite
        fh.write(data)
    return stored, hashlib.sha256(data).hexdigest()


def resolve_stored(uploads_dir: Path, stored_name: str) -> Path:
    root = uploads_dir.resolve()
    path = (root / stored_name).resolve()
    if not path.is_relative_to(root):
        raise IngestionError("Invalid stored file path.")
    return path


# ---------------------------------------------------------------- spreadsheet reading

@dataclass
class Cell:
    text: str | None
    kind: str  # text | number | date_cell | bool | empty
    coord: str


@dataclass
class Table:
    sheets: list[str]
    sheet: str | None
    header_row: int  # 1-based row number in the file
    headers: list[str]
    rows: list[tuple[int, list[Cell]]]  # (1-based row number, cells)
    truncated: bool = False
    notes: list[str] = field(default_factory=list)


def _col_letter(idx: int) -> str:
    out = ""
    idx += 1
    while idx:
        idx, rem = divmod(idx - 1, 26)
        out = chr(65 + rem) + out
    return out


def _cell_from_value(value, coord: str) -> Cell:
    if value is None:
        return Cell(None, "empty", coord)
    if isinstance(value, bool):
        return Cell(str(value).upper(), "bool", coord)
    if isinstance(value, datetime):
        if value.time() == time(0, 0):
            return Cell(value.date().isoformat(), "date_cell", coord)
        return Cell(value.isoformat(sep=" "), "date_cell", coord)
    if isinstance(value, date):
        return Cell(value.isoformat(), "date_cell", coord)
    if isinstance(value, int):
        return Cell(str(value), "number", coord)
    if isinstance(value, float):
        return Cell(_float_text(value), "number", coord)
    if isinstance(value, Decimal):
        return Cell(format(value, "f"), "number", coord)
    text = str(value)
    if not text.strip():
        return Cell(None, "empty", coord)
    return Cell(text, "text", coord)


def _float_text(value: float) -> str:
    """Exact-as-stored text for a spreadsheet number, without binary float noise.

    ``repr`` gives the shortest text that round-trips to the stored double.
    If that is a long tail like 1838.1399999999999 (a stored computation
    artefact) and rounding to 6 places is within 1e-9, the rounded text is used.
    """
    if value.is_integer():
        return str(int(value))
    d = Decimal(repr(value))
    rounded = d.quantize(Decimal("0.000001")).normalize()
    if abs(d - rounded) < Decimal("1e-9"):
        return format(rounded, "f")
    return format(d, "f")


def _decode_csv(data: bytes) -> str:
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1")


def _read_csv_rows(data: bytes) -> list[list[Cell]]:
    text = _decode_csv(data)
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        delimiter = dialect.delimiter
    except csv.Error:
        delimiter = ","
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    rows: list[list[Cell]] = []
    for r_idx, raw in enumerate(reader, start=1):
        if r_idx > MAX_SPREADSHEET_ROWS + HEADER_SCAN_ROWS:
            break
        rows.append([
            Cell(v if v.strip() else None, "text" if v.strip() else "empty", f"{_col_letter(c)}{r_idx}")
            for c, v in enumerate(raw)
        ])
    return rows


def _read_xlsx_rows(path: Path, sheet: str | None) -> tuple[list[str], str, list[list[Cell]]]:
    try:
        wb = load_workbook(path, read_only=True, data_only=True)
    except (zipfile.BadZipFile, KeyError, OSError, ValueError) as exc:
        raise IngestionError("The workbook could not be opened. It may be damaged or password-protected.") from exc
    try:
        names = list(wb.sheetnames)
        chosen = sheet if sheet in names else names[0]
        ws = wb[chosen]
        rows: list[list[Cell]] = []
        for r_idx, values in enumerate(ws.iter_rows(values_only=True), start=1):
            if r_idx > MAX_SPREADSHEET_ROWS + HEADER_SCAN_ROWS:
                break
            rows.append([_cell_from_value(v, f"{chosen}!{_col_letter(c)}{r_idx}") for c, v in enumerate(values)])
        return names, chosen, rows
    finally:
        wb.close()


def _header_score(cells: list[Cell], alias_index: dict[str, str]) -> int:
    return sum(1 for c in cells if c.text and normalize_header(c.text) in alias_index)


def _detect_header_row(rows: list[list[Cell]], alias_index: dict[str, str]) -> int:
    best_row, best_score = 0, -1
    for idx, cells in enumerate(rows[:HEADER_SCAN_ROWS]):
        score = _header_score(cells, alias_index)
        if score > best_score:
            best_row, best_score = idx, score
    if best_score >= 2:
        return best_row + 1
    for idx, cells in enumerate(rows[:HEADER_SCAN_ROWS]):
        if sum(1 for c in cells if c.text) >= 2:
            return idx + 1
    return 1


def _unique_headers(cells: list[Cell], width: int) -> list[str]:
    headers: list[str] = []
    seen: dict[str, int] = {}
    for i in range(width):
        text = cells[i].text.strip() if i < len(cells) and cells[i].text else ""
        label = " ".join(text.split()) or f"Column {_col_letter(i)}"
        if label in seen:
            seen[label] += 1
            label = f"{label} ({seen[label]})"
        else:
            seen[label] = 1
        headers.append(label)
    return headers


def read_table(path: Path, kind: str, template: Template, sheet: str | None = None,
               header_row: int | None = None) -> Table:
    if kind == "csv":
        rows = _read_csv_rows(path.read_bytes())
        sheets, chosen = [], None
    elif kind == "xlsx":
        sheets, chosen, rows = _read_xlsx_rows(path, sheet)
        if sheet is None and len(sheets) > 1:
            chosen, rows = _best_sheet(path, sheets, template, chosen, rows)
    else:
        raise IngestionError(f"{kind} is not a spreadsheet")
    alias_index = template.alias_index()
    if not rows:
        return Table(sheets, chosen, 1, [], [], notes=["The sheet is empty."])
    h_row = header_row if header_row and 1 <= header_row <= len(rows) else _detect_header_row(rows, alias_index)
    width = max((len(r) for r in rows), default=0)
    # Ignore trailing columns that are empty everywhere.
    while width > 0 and all(len(r) < width or r[width - 1].text is None for r in rows):
        width -= 1
    headers = _unique_headers(rows[h_row - 1], width)
    data_rows: list[tuple[int, list[Cell]]] = []
    for r_idx in range(h_row, len(rows)):
        cells = rows[r_idx][:width]
        cells += [Cell(None, "empty", "") for _ in range(width - len(cells))]
        if all(c.text is None for c in cells):
            continue
        data_rows.append((r_idx + 1, cells))
    truncated = len(data_rows) > MAX_SPREADSHEET_ROWS
    return Table(sheets, chosen, h_row, headers, data_rows[:MAX_SPREADSHEET_ROWS], truncated)


def _best_sheet(path: Path, sheets: list[str], template: Template, first: str, first_rows):
    alias_index = template.alias_index()
    best = (first, first_rows, max((_header_score(r, alias_index) for r in first_rows[:HEADER_SCAN_ROWS]), default=0))
    for name in sheets:
        if name == first:
            continue
        _, _, rows = _read_xlsx_rows(path, name)
        score = max((_header_score(r, alias_index) for r in rows[:HEADER_SCAN_ROWS]), default=0)
        if score > best[2]:
            best = (name, rows, score)
    return best[0], best[1]


# ---------------------------------------------------------------- mapping

def header_signature(headers: list[str]) -> str:
    joined = "|".join(sorted(normalize_header(h) for h in headers if not h.startswith("Column ")))
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:24]


def suggest_mapping(headers: list[str], template: Template) -> dict[str, dict]:
    """field -> {"column": heading or None, "reason": text}. Exact alias matches only."""
    index = template.alias_index()
    suggestions: dict[str, dict] = {f.name: {"column": None, "reason": None} for f in template.fields}
    for header in headers:
        key = normalize_header(header)
        field_name = index.get(key)
        if field_name and suggestions[field_name]["column"] is None:
            suggestions[field_name] = {"column": header, "reason": f"heading '{header}' matches a configured alias"}
    return suggestions


def mapping_problems(mapping: dict[str, str | None], headers: list[str], template: Template,
                     default_currency: str | None) -> list[str]:
    problems = []
    used: dict[str, str] = {}
    for field_name, column in mapping.items():
        if field_name not in template.field_names:
            problems.append(f"Unknown field '{field_name}'.")
            continue
        if column is None:
            continue
        if column not in headers:
            problems.append(f"Column '{column}' is not in this file.")
        if column in used:
            problems.append(f"Column '{column}' is mapped to both {template.label(used[column])} "
                            f"and {template.label(field_name)}.")
        used[column] = field_name
    currency_field = template.currency_field
    for f in template.fields:
        if not f.required:
            continue
        if mapping.get(f.name):
            continue
        if f.name == currency_field and default_currency:
            continue
        problems.append(f"Required field '{f.label}' has no column.")
    if default_currency and default_currency not in template.currency.allowed:
        problems.append(f"Default currency '{default_currency}' is not in the configured list.")
    return problems


def preview_payload(table: Table, template: Template, mapping: dict[str, str | None]) -> dict:
    sample_rows = [
        {"row": r, "cells": [c.text for c in cells]} for r, cells in table.rows[:MAX_PREVIEW_ROWS]
    ]
    date_analysis = None
    for f in template.fields:
        if f.type == "date" and mapping.get(f.name) in table.headers:
            col = table.headers.index(mapping[f.name])
            values = [cells[col].text or "" for _, cells in table.rows if cells[col].kind != "date_cell"]
            date_cells = sum(1 for _, cells in table.rows if cells[col].kind == "date_cell")
            analysis = analyse_date_column(values)
            analysis["date_cells"] = date_cells
            analysis["field"] = f.name
            date_analysis = analysis
    return {
        "sheets": table.sheets,
        "sheet": table.sheet,
        "header_row": table.header_row,
        "headers": table.headers,
        "rows": sample_rows,
        "total_rows": len(table.rows),
        "truncated": table.truncated,
        "notes": table.notes,
        "date_analysis": date_analysis,
        "signature": header_signature(table.headers),
    }
