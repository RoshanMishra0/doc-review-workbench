# Document Review Workbench

A local web app that turns business documents and spreadsheets into structured records, checks them against configurable rules, compares them with a reference spreadsheet, and gives a person a clear queue to correct, approve or exclude records before exporting the result to Excel.

The first workflow template is **supplier invoices vs a purchase register**:

> upload invoices (PDF, CSV or XLSX) and the purchase register → extract invoice header fields → validate → match conservatively against the register → review and correct → export an XLSX review workbook.

Status: a working first version for demos and paid pilots on synthetic or carefully chosen data. It is **not production-ready**: there is no login, it is single-user, and it has only been tested on the synthetic data in this repository.

## Contents

- [Requirements](#requirements)
- [Setup and run on Windows PowerShell](#setup-and-run-on-windows-powershell)
- [Setup and run on macOS or Linux](#setup-and-run-on-macos-or-linux)
- [Development mode](#development-mode)
- [Tests](#tests)
- [Sample data](#sample-data)
- [How it works](#how-it-works)
- [Supported inputs](#supported-inputs)
- [Known limitations](#known-limitations)
- [Implemented vs proposed](#implemented-vs-proposed)
- Other docs: [Template configuration guide](docs/TEMPLATE_GUIDE.md), [Three-minute demo script](docs/DEMO_SCRIPT.md), [Sample data and expected outcomes](sample_data/README.md)

## Requirements

Tested with these versions. Nothing needs a paid API, a cloud account or an AI subscription.

| Component | Version tested |
| --- | --- |
| Python | 3.14.3 (3.11 or later should work but was not tested) |
| Node.js / npm | 24.14.0 / 11.12.0 (only needed to build the UI) |
| FastAPI / Starlette / Uvicorn | 0.164.0 / 1.10.0 / 0.54.0 |
| Pydantic | 2.14.3 |
| openpyxl (XLSX) | 3.1.5 |
| pypdf (PDF text) | 7.1.1 |
| python-multipart | 0.0.34 |
| pytest / httpx (tests) | 9.2.0 / 0.28.1 |
| fpdf2 / Pillow (sample generator only) | 2.9.0 / 13.0.0 |
| React / React DOM | 19.3.1 |
| Vite / @vitejs/plugin-react | 8.3.8 / 6.3.0 |
| TypeScript | 7.0.2 |

Exact pins are in `backend/requirements.txt`, `backend/requirements-dev.txt` and `frontend/package-lock.json`. SQLite comes with Python.

## Setup and run on Windows PowerShell

From the repository folder (`doc-review-workbench`):

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements-dev.txt
cd ..\frontend
npm ci
npm run build
cd ..\backend
.\.venv\Scripts\python run_server.py
```

Then open http://127.0.0.1:8000 in a browser.

The same steps as scripts (they stop on the first error):

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
powershell -ExecutionPolicy Bypass -File scripts\start.ps1
```

Useful options for `run_server.py`:

- `--port 8010` to use another port.
- `--data-dir D:\demo-data` to keep the database and stored uploads somewhere else. The default is `backend\data`. A separate folder per client or demo keeps their data apart.
- The server binds to `127.0.0.1` (this computer only). `--host` can change that, but there is no login, so don't expose it on a network.

Stop the server with Ctrl+C. Everything you did is in `backend\data\workbench.db` and is there when you start again.

## Setup and run on macOS or Linux

```bash
cd backend && python3 -m venv .venv && .venv/bin/python -m pip install -r requirements-dev.txt
cd ../frontend && npm ci && npm run build
cd ../backend && .venv/bin/python run_server.py
```

## Development mode

Run the API and the Vite dev server side by side. Vite proxies `/api` to the backend.

```powershell
cd backend; .\.venv\Scripts\python run_server.py
```

```powershell
cd frontend; npm run dev
```

Then open http://127.0.0.1:5173. API docs (OpenAPI) are at http://127.0.0.1:8000/api/docs.

## Tests

```powershell
cd backend
.\.venv\Scripts\python -m pytest
```

92 tests cover the behaviour that could produce a wrong business result: column mapping with different headings, leading zeros, date parsing and ambiguous dates, Decimal arithmetic and tolerance boundaries, duplicate detection, equal amounts that must not match, ambiguous register rows, unmatched records on both sides, unsupported/image-only/damaged PDFs, correction followed by revalidation and rematching, approvals withdrawn by corrections, persistence across a restart, export agreeing with the reviewed records, formula-safe export, invalid template configurations, a second differently shaped template (expense claims) running through the same code, and an end-to-end run of both sample datasets against their documented expected outcomes.

Frontend type-check and build: `cd frontend; npm run build`.

## Sample data

All sample data is synthetic: fictional companies, addresses, tax IDs and amounts. Each PDF carries a "SYNTHETIC DOCUMENT" footer.

- In the app, press **Load sample dataset** on the Batches page and choose a set. The loader reads the committed files from `sample_data/` and passes them through the same upload, mapping and processing code as a manual upload.
  - **Harbor Lane Supplies**: 18 invoice PDFs in three layouts plus an XLSX purchase register. Processes fully on load.
  - **Meridian Workshop Services**: a CSV invoice listing and a CSV register with different headings. The register stops at column mapping on purpose: map **Party** to Supplier name, **Doc Total** to Total amount, and choose **MM/DD/YYYY** as the date format. If you save the mapping, the next load of this sample applies it automatically.
- To regenerate the files: `backend\.venv\Scripts\python sample_data\generate_samples.py` (run from the repository root).
- Every scenario and its expected result is documented in [sample_data/README.md](sample_data/README.md).

## How it works

```
upload ─► ingestion ─► extraction ─► normalization ─► validation ─► matching ─► review ─► export
          (store,       (PDF layout   (dates, money,   (configured   (identity,   (corrections,
           type check,   parsers,      names, ids)      rule types)   compare,     approvals,
           sheets,       spreadsheet                                  explain)     history)
           mapping)      mapping)
```

Backend modules (`backend/app/`):

| Module | Job |
| --- | --- |
| `template_config.py` + `template_configs/*.json` | Template schema and loading. Fields, aliases, date and currency settings, rule definitions, matching keys and tolerances live in JSON and are validated on startup. |
| `ingestion.py` | Upload type checks, generated storage paths, CSV/XLSX reading, sheet and heading-row detection, alias suggestions, mapping checks. |
| `extraction/` | `pdf_reader.py` reads the PDF text layer. `invoice_layouts.py` holds deterministic parsers for the documented layouts. `registry.py` picks a layout or rejects the file with a reason. `base.py` is the interface another parser (or a future LLM extractor) would implement. |
| `normalization.py` | Documented parsing of dates, money (Decimal), currencies, supplier names and invoice numbers. |
| `validation.py` | The fixed set of rule types, applied per record and per batch (duplicates). |
| `matching.py` | Conservative identity matching, field comparison and plain-language explanations. |
| `services.py` | Processing and review operations on SQLite. Recomputes outcomes after every correction, exclusion or link, and withdraws approvals whose outcome changed. |
| `export.py` | The XLSX review workbook. |
| `samples.py` | Loads the sample sets through the normal pipeline. |
| `api.py`, `main.py` | FastAPI routes, error handling, security headers, serving the built UI. |

Storage: one SQLite file (`workbench.db`) with batches, files, PDF page text, records, issues, manual links, mapping profiles and a history table. Uploaded files are stored once under generated names in `data/uploads/batch_<id>/` and never modified. Extracted values are stored exactly as read; corrections are stored separately, so the original value is always available.

Processing outcomes and review decisions are separate. A record has a validation status (checks passed / passed with warnings / failed checks), a match status, and a review status (awaiting review / approved / excluded). A record can be "Matched" and still "Awaiting review".

Frontend (`frontend/src/`): React + TypeScript, no UI framework. Views: Batches, Import (upload, template details, column mapping), Records (filters and search), Review (fields, checks, matching, decision, history, source evidence), Export.

## Supported inputs

- **PDF invoices** with a text layer, in three documented layouts: Classic tax invoice, Modern invoice and Billing statement (see the [template guide](docs/TEMPLATE_GUIDE.md#pdf-layouts)). One invoice per PDF, up to 50 pages.
- **CSV** in UTF-8 (with or without BOM) or Windows-1252, delimiter detected among comma, semicolon, tab and pipe.
- **XLSX** with worksheet selection and heading-row detection. Real date cells are read as dates. Values from formulas are read from the workbook's cached results.
- 20 MB per file, 100 files per upload.

Rejected with a reason and listed in the batch and the export: other file types, legacy `.xls`, empty files, password-protected PDFs, damaged PDFs, PDFs without a text layer (OCR is not supported), PDFs in other layouts, and PDFs uploaded as the register.

## Known limitations

- PDF extraction only works for the three documented layouts. Real supplier invoices will mostly need new layout parsers or a different extractor.
- No OCR. Scanned invoices are rejected with an explanation.
- Invoice header fields only; no line items.
- Matching is one invoice to one register row. No partial payments, credit notes, bank settlement or many-to-many reconciliation.
- Supplier matching uses only the documented normalization and explicit aliases from the template file. Aliases are per template, not per business, and are edited in JSON, not in the UI.
- Decimal separator is a dot and grouping is a comma. European formats like `1.234,56` are reported as invalid, not guessed.
- A spreadsheet's mapping can't be changed after it is processed. Remove the file and upload it again.
- Single user, no login, no roles, no audit signatures. History records "reviewer" as the actor.
- Validation and matching are recomputed for the whole batch on each change. That is fine for hundreds or a few thousand records; very large batches were not tested.
- The UI was smoke-tested on Windows 10 in the Claude desktop app's built-in browser at a 1440x900 viewport. Other browsers and small screens were not tested; the layout is desktop-first.
- The checks don't establish tax compliance, payment status, fraud or accounting correctness.

## Implemented vs proposed

| Capability | Status |
| --- | --- |
| Batches, uploads, rejected-file accounting | Implemented |
| CSV/XLSX preview, sheet and heading row, alias suggestions, editable mapping, saved reusable mappings | Implemented |
| Visible date-format and default-currency assumptions per source, with a date-format check on the preview | Implemented |
| Text PDF extraction for three synthetic layouts, with per-field evidence and page text | Implemented |
| Image-only, damaged, protected and unsupported PDFs routed to rejection with reasons | Implemented |
| Configurable template (JSON) with a fixed set of rule types, validated on startup | Implemented |
| Required, date, money, net + tax = total, currency and duplicate checks with Decimal arithmetic | Implemented |
| Conservative matching with explanations, ambiguity handling and manual linking | Implemented |
| Corrections, revert, approve (note required with open issues), exclude with reason, reopen, notes | Implemented |
| Approvals withdrawn automatically when a recompute changes an approved outcome | Implemented |
| History of extractions, corrections, decisions and system changes | Implemented |
| XLSX export with seven sheets, formula-safe text, numeric amounts and real dates | Implemented |
| Synthetic dataset generator, committed fixtures and documented expected outcomes | Implemented |
| Second template (for example expense-register validation) | Proposed. The template and extractor structure is ready for it; no second template exists yet. |
| Template and alias editing in the UI, per-business settings | Proposed |
| AI/LLM extraction adapter behind the extractor interface | Proposed (optional, not started) |
| OCR for scanned documents | Proposed |
| Line-item extraction | Proposed |
| Authentication, multiple users, roles | Proposed |
| Accounting-system integrations, email intake, notifications | Not planned for this version |
