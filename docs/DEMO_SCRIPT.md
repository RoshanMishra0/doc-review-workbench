# Three-minute demo script

Before the demo: start the app (`scripts\start.ps1` or `python run_server.py`), open http://127.0.0.1:8000, and delete old demo batches if you want a clean list. For a fresh database use `python run_server.py --data-dir <empty folder>`.

Say once at the start: *all data here is synthetic, fictional companies.*

## 0:00 - Load (20 s)

1. On **Batches**, click **Load sample dataset**, choose **Harbor Lane Supplies**, click **Load**.
2. Say: *"18 invoice PDFs in three layouts and a purchase register in Excel just went through the same upload and processing path as any file you'd upload. The register sat on the second sheet under a title row; the app found the sheet and the heading row from the column names."*

## 0:20 - Records (40 s)

1. The **Records** tab opens. Point at the chips: 7 matched, 1 mismatched, 2 missing from the register, 3 ambiguous, 2 needing correction.
2. Say: *"Every count comes from the data. Nothing is matched on amount alone: kestrel 000462 has exactly the same total as a register row, but a different invoice number, so it's reported missing, not matched."*
3. Point at orchid OLC-1450: *"Matched, but failed checks: the register agrees with the invoice, yet net plus tax doesn't equal the total. Matching and validation are separate on purpose."*
4. Optional: switch **Show** to *Purchase register rows* and filter *Register row without uploaded invoice* to show 000463 and MSU-88120. Then go to **Import** to show the scanned MSU-88120 PDF was rejected because OCR isn't supported.

## 1:00 - Inspect and correct (60 s)

1. Back on Records with *Supplier invoices*, click **tarnwood_TP-5520** (Needs correction).
2. Show the right panel: the PDF's text layer, with each line that produced a value labelled. Hover a field to highlight its source line. Point out there is no tax line in the PDF and the field says **Missing**, not a guess.
3. Show **Matching**: *"Same supplier, invoice number and currency as register row 10, but tax is missing, so the comparison can't complete."*
4. Click **Correct values**, type `2,700.00` for Tax amount, add a note ("tax confirmed with supplier"), click **Save and rerun checks**.
5. Result: checks pass, Matched, the field shows **User corrected** and the extracted value is still recorded as "Not found". The matching table now shows every field the same.

## 2:00 - Approve and resolve (35 s)

1. Click **Approve**. The history shows the correction and the approval with times.
2. Optional, if time: open **quillmark_QS-0091_resent.pdf**, type "duplicate re-sent by supplier", click **Exclude with reason**. The original copy becomes Matched automatically.
3. Say: *"If anyone later corrects a value that changes an approved record's outcome, the approval is withdrawn automatically and the history says why."*

## 2:35 - Restart and export (25 s)

1. Stop the server (Ctrl+C) and start it again. Refresh the page: the batch, correction and approval are all still there.
2. Open **Export**, click **Download XLSX**. Show the sheets: All records, Approved, Outstanding exceptions, Unmatched register rows, Rejected files, Review history. Each row has its source file and page or row reference.
3. Close: *"Field names, column aliases, rules, tolerances and matching keys are in a JSON template, so the same app can run another document workflow for another business."*

## If asked

- *Is this AI?* No. PDFs are read by deterministic parsers for documented layouts. Unknown layouts are rejected, not guessed. An AI extractor could be added behind the same interface later.
- *What about a different layout?* Show the Lumen Ridge quotation in the rejected files. A new layout needs a parser (or another extractor).
- *Different spreadsheet headings?* Load the **Meridian** sample: its register stops at the mapping screen, with two unknown headings and a warning that its dates are month-first.
