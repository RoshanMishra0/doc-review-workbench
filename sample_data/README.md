# Synthetic sample data

Everything here is **synthetic**. The companies, people, addresses, tax IDs ("SYN-TAX-0000") and amounts are invented. Each PDF has a "SYNTHETIC DOCUMENT" footer and the register workbook has a "Read me" sheet that says so.

## Regenerate

From the repository root, with the backend virtual environment:

```powershell
backend\.venv\Scripts\python sample_data\generate_samples.py
```

The generator is reproducible: fixed values, a fixed PDF creation date, and XLSX files rewritten with fixed zip timestamps and a fixed "modified" property. Two runs produce byte-identical files. The generated files are committed so the demo works without running it.

Outputs:

| File | What it is |
| --- | --- |
| `harbor_lane/invoices/*.pdf` | 18 supplier invoice PDFs for the fictional buyer Harbor Lane Supplies Pvt Ltd |
| `harbor_lane/purchase_register.xlsx` | Harbor Lane's purchase register: a "Read me" sheet first, then "Register 2025-03" with a title row, a blank row and headings on row 3 |
| `meridian/supplier_invoice_listing.csv` | An invoice listing for the fictional buyer Meridian Workshop Services |
| `meridian/purchase_register.csv` | Meridian's register, with different headings and month-first dates |
| `brightwater/expense_claims_export.csv` | 12 expense claims from the fictional Brightwater Design Studio Ltd (expense-claims template) |
| `brightwater/expense_register.xlsx` | Brightwater finance's expense register, plus a "Notes" sheet that says it's synthetic |
| `manifest.json` | Which files each sample set loads, and as which role. Read by the app's sample loader. |
| `expected_outcomes.json` | The expected results below in machine-readable form. **Used only by the tests.** The app never reads it; every result in the UI comes from real extraction and matching. |

## Two businesses, two sets of headings

| Field | Harbor Lane register (XLSX) | Meridian listing (CSV) | Meridian register (CSV) |
| --- | --- | --- | --- |
| Supplier name | Vendor Name | Supplier | **Party** (not an alias) |
| Invoice number | Bill No. | Inv No | Supplier Invoice Ref |
| Invoice date | Bill Date (real date cells) | Inv Date (`DD-MM-YYYY` text) | Supplier Invoice Date (`MM/DD/YYYY` text) |
| Currency | Currency | Ccy | Curr. |
| Net amount | Taxable Value | Amount excl. tax | Basic Value |
| Tax amount | GST Amount | Tax | Tax Value |
| Total amount | Bill Total | Amount incl. tax | **Doc Total** (not an alias) |

Harbor Lane's register and Meridian's listing map completely from the template aliases, so the sample loader confirms them automatically and says so in the history. Meridian's register has two unknown headings and stops at the mapping screen, as an upload would. The mapping screen also warns that only 3 of its 8 dates fit DD/MM/YYYY while all 8 fit MM/DD/YYYY.

## Harbor Lane: expected results after loading

### Invoices (15 records from 15 supported PDFs)

| File | Layout | Scenario | Match status | Issues |
| --- | --- | --- | --- | --- |
| apex_INV-00123.pdf | Classic | Clean match; register writes "Private Limited" instead of "Pvt. Ltd." | Matched | none |
| bluecrest_BOS-2025-0042.pdf | Classic | Clean match | Matched | none |
| kestrel_000457.pdf | Modern | Clean match; all-digit invoice number with leading zeros | Matched | none |
| corvane_CS-7781.pdf | Modern | Clean match in USD | Matched | none |
| sablefin_SE-2025-118.pdf | Statement | Clean match through the explicit alias "Sablefin Electrical Works" | Matched | none |
| quillmark_QS-0091.pdf | Classic | Duplicate invoice | Ambiguous | Possible duplicate |
| quillmark_QS-0091_resent.pdf | Classic | The same invoice sent again | Ambiguous | Possible duplicate |
| tarnwood_TP-5520.pdf | Classic | Missing required field: no tax line | Needs correction | Tax amount missing |
| velanto_VFS-3307.pdf | Classic | Invalid date 31/02/2025 (register: 28/02/2025) | Needs correction | Invalid date |
| orchid_OLC-1450.pdf | Classic | Arithmetic inconsistency: 9,500.00 + 475.00 ≠ 10,075.00. The register repeats the same figures. | **Matched** | Arithmetic inconsistency (shows that matching and validation are separate) |
| apex_INV-00131.pdf | Classic | Amount mismatch: invoice total 12,500.00, register 12,050.00 | Mismatched | Mismatch on net, tax and total |
| bluecrest_BOS-2025-0057.pdf | Classic | Invoice absent from the register | Missing from purchase register | |
| kestrel_000462.pdf | Modern | Equal amounts, different invoices: 23,100.00 like 000457 and register row 000463, but no row has 000462 | Missing from purchase register | |
| tarnwood_TP-5531.pdf | Classic | Multiple possible matches: TP-5531 is in the register twice | Ambiguous | |
| velanto_VFS-3312.pdf | Statement | Clean match | Matched | none |

Totals: 7 matched, 1 mismatched, 2 missing from purchase register, 3 ambiguous, 2 needing correction.

Because three PDFs are rejected, the batch is marked **incomplete**: a banner names them and the export's Summary says "Inputs fully imported: NO". Removing the three files (Import tab) makes the batch complete, since a removed file is a recorded reviewer decision.

### Rejected files (3)

| File | Reason code | Scenario |
| --- | --- | --- |
| lumenridge_quotation_Q-219.pdf | unsupported_layout | Readable text, but a quotation layout no parser supports |
| scan_marlow_MSU-88120.pdf | image_only | Scan with no text layer. Message says OCR is not supported. |
| invoice_damaged.pdf | damaged | PDF header followed by broken content |

### Register rows (15)

| Row | Invoice number | Match status |
| --- | --- | --- |
| 4 | INV-00123 | Matched |
| 5 | BOS/2025/0042 | Matched |
| 6 | 000457 | Matched |
| 7 | CS-7781 | Matched |
| 8 | SE-2025-118 | Matched |
| 9 | QS-0091 | Ambiguous (claimed by the two duplicate invoices) |
| 10 | TP-5520 | Paired invoice needs correction |
| 11 | VFS-3307 | Paired invoice needs correction |
| 12 | OLC-1450 | Matched (and fails the arithmetic check itself) |
| 13 | INV-00131 | Mismatched |
| 14 | 000463 | Register row without invoice (same amount as 000462) |
| 15 | TP-5531 | Ambiguous |
| 16 | TP-5531 | Ambiguous |
| 17 | VFS-3312 | Matched |
| 18 | MSU-88120 | Register row without invoice (its invoice was the rejected scan) |

Rows 14 and 18 also say that not every invoice file was imported, so a matching invoice may be in one of the rejected files. For MSU-88120 that is exactly the case.

### What review actions change

- Correct tarnwood_TP-5520 tax to `2,700.00` → checks pass, Matched with row 10.
- Correct velanto_VFS-3307 date to `28/02/2025` → Matched with row 11.
- Exclude quillmark_QS-0091_resent.pdf as a duplicate → quillmark_QS-0091.pdf becomes Matched with row 9.
- Link tarnwood_TP-5531 to row 15 → Matched; row 16 becomes "Register row without invoice".

## Meridian: expected results after mapping the register

Map **Party** → Supplier name, **Doc Total** → Total amount, keep the five suggestions, choose **MM/DD/YYYY**, then Process.

| Listing row | Invoice number | Scenario | Match status |
| --- | --- | --- | --- |
| 2 | FT/24-25/0310 | Register supplier "Ferrowave Tools Pvt Ltd" vs "Ferrowave Tools" | Matched |
| 3 | FT/24-25/0322 | | Matched |
| 4 | 0004471 | Leading zeros in CSV text | Matched |
| 5 | 0004480 | Invoice date 12 Mar 2025, register 13 Mar 2025 | Mismatched |
| 6 | PSG-221 | Not in the register | Missing from purchase register |
| 7 | RC-0098 | Currency cell blank | Needs correction (the register row RC-0098 shows "Register row without invoice" with a hint pointing at this record) |
| 8 | TF-5501 | | Matched |
| 9 | FT/24-25/0331 | | Matched |

Register rows: 5 matched, 1 mismatched, 2 without an uploaded invoice (RC-0098 and HF-7710). Correcting RC-0098's currency to `INR` makes it Matched.

If DD/MM/YYYY is left selected by mistake, five register dates are reported as invalid and others are read as different days, which shows up as date mismatches. Nothing is silently reinterpreted.

Until the register is mapped and processed, the batch is marked incomplete and every listing invoice says the purchase register isn't fully imported.

## Brightwater Design Studio: the expense-claims template

Loads with the **Expense claims vs expense register** template. Both files map automatically from the template's aliases and the batch processes on load.

| Field | Claims export (CSV) | Expense register (XLSX) |
| --- | --- | --- |
| Employee | Employee | Staff member |
| Claim reference | Claim ID | Claim no |
| Expense date | Expense date (`DD/MM/YYYY` text) | Date incurred (real date cells) |
| Category | Category | Cost category |
| Currency | Currency | CCY |
| Amount | Amount claimed | Amount approved |

Not mapped: Description (claims) and Cost centre (register).

### Claims (12)

| Row | Claim | Employee | Scenario | Match status | Issues |
| --- | --- | --- | --- | --- | --- |
| 2 | EXP-1001 | Asha Rao | Clean match | Matched | none |
| 3 | EXP-1002 | Tom Okafor | Clean match | Matched | none |
| 4 | EXP-1003 | Mei Lin | Clean match | Matched | none |
| 5 | EXP-1004 | Asha Rao | Claimed £84.00, finance approved £80.00 | Mismatched | Mismatch |
| 6 | EXP-1005 | Tom Okafor | Amount left blank | Needs correction | Missing required value |
| 7 | EXP-1006 | Mei Lin | Impossible date 30/02/2025 (register: 20/02/2025) | Needs correction | Invalid date |
| 8 | EXP-1007 | Daniel Price | Claim submitted twice | Ambiguous | Possible duplicate |
| 9 | EXP-1007 | Daniel Price | The second submission | Ambiguous | Possible duplicate |
| 10 | EXP-1008 | Sara Ahmed | Claimed in EUR, register has GBP | Missing from expense register (with a currency hint) | |
| 11 | EXP-1009 | Asha Rao | Category Meals, register says Entertainment | Mismatched | Mismatch |
| 12 | EXP-1010 | Tom Okafor | Same £42.60 as EXP-1001 and register row EXP-1012, but no register row for EXP-1010 | Missing from expense register | |
| 13 | EXP-1011 | Mei Lin | Register has EXP-1011 twice | Ambiguous | |

Totals: 3 matched, 2 mismatched, 2 missing from expense register, 3 ambiguous, 2 needing correction.

### Register rows (12)

| Row | Claim | Match status |
| --- | --- | --- |
| 2-4 | EXP-1001 to EXP-1003 | Matched |
| 5 | EXP-1004 | Mismatched |
| 6 | EXP-1005 | Paired claim needs correction |
| 7 | EXP-1006 | Paired claim needs correction |
| 8 | EXP-1007 | Ambiguous (claimed by the two duplicate submissions) |
| 9 | EXP-1008 | Register row without claim (GBP; the claim is EUR) |
| 10 | EXP-1009 | Mismatched |
| 11, 12 | EXP-1011 | Ambiguous |
| 13 | EXP-1012 (Priya Nair) | Register row without claim |

### What review actions change

- Correct EXP-1005 amount to `22.50` → Matched with row 6.
- Correct EXP-1006 date to `20/02/2025` → Matched with row 7.
- Exclude the second EXP-1007 submission → the first becomes Matched with row 8.
- Link EXP-1011 to row 11 → Matched; row 12 becomes "Register row without claim".
