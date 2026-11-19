# Changelog

## 0.2.0 (2026-11-19)

### Fixed

- **Approvals survived material changes.** An approved record kept its approval when the record it was paired with changed but the match status and issue types stayed the same. Example: a register total corrected from 12,050.00 to 12,060.00 on a pair that was still mismatched. The approval basis now also covers the compared values, the match explanation, the candidates and the full issue messages. The history note says what changed, for example "total amount comparison changed from ₹12,500.00 vs ₹12,050.00 to ₹12,500.00 vs ₹12,060.00". Hints are left out because they never change an outcome.
- **Removing a file kept its content.** The stored file and its extracted text stayed on disk and could still be opened. Removal now deletes the stored copy, the page text, the file's records (with their issues and manual links) and the field values copied from it into the history, all in one transaction. The file stays listed as removed (name, size, SHA-256, upload and removal times), and opening it returns 410 Gone.
- **Large spreadsheets were imported in part.** A sheet over the row limit had its first 20,000 rows imported and was marked processed. Import is now all or nothing: an over-limit sheet is refused at the mapping step and rejected at processing. Detection also no longer depends on where the heading row is; before, a heading far down the sheet could hide extra rows.

### Added

- **Batch completeness.** A banner on every batch page names any file that isn't fully imported (waiting for mapping, not processed, or rejected). The export's Summary sheet says "Inputs fully imported: Yes/NO" and lists those files. "Missing from register" and "register row without invoice" results say when a file on the other side wasn't imported.
- **Second template: expense claims vs expense register** (`expense_claims.json`). It's selectable in the New batch dialog and comes with the synthetic sample "Brightwater Design Studio expenses" and documented expected results.
- **GitHub Actions CI** (`.github/workflows/ci.yml`): backend tests on Python 3.14, and the frontend type-check and build on Node 24.
- `DRW_MAX_SHEET_ROWS` sets the spreadsheet row limit (default 20,000).
- Status labels now use the template's own words, so the expense template reads "Missing from expense register" and "Register row without claim".

### Changed

- Some label text changed: "Missing from register" is now "Missing from purchase register", and "Register row without uploaded invoice" is now "Register row without invoice". The batch list columns are now Records, Reference rows and Records reviewed.
- The sample generator is byte-reproducible. `harbor_lane/purchase_register.xlsx` was regenerated once as a result; its content is unchanged.
- The database schema is now version 2 (adds `files.removed_at`). Existing databases are upgraded automatically on start.
- Tests: 92 became 113.

## 0.1.0 (2026-11-18)

First version: supplier invoices vs purchase register, from upload to reviewed Excel export, with synthetic sample data.
