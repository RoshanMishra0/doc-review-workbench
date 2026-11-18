# Template configuration guide

A template describes one workflow: what a record looks like, how source columns are recognised, which checks run, and how records are matched against the reference spreadsheet. Templates are JSON files in `backend/app/template_configs/` (or in the folder named by the `DRW_TEMPLATE_DIR` environment variable). They are validated when the server starts; a broken template stops the server with a message that names the problem.

The shipped template is `supplier_invoice.json`. Business-specific names, aliases, rules and keys belong here, not in code.

## Top-level keys

| Key | Meaning |
| --- | --- |
| `id`, `version`, `name`, `description` | Identity of the template. Batches record the id and version they were created with. |
| `synthetic_note` | Text shown in the UI and export that states what the checks do and don't cover. |
| `roles` | Exactly two roles: `invoice` (the documents being checked) and `reference` (the register they are compared with). Each has a `label`, `plural`, `description` and the file kinds it `accepts` (`pdf`, `csv`, `xlsx`). |
| `fields` | The canonical fields. See below. |
| `dates` | `default_order`: the date format proposed for new spreadsheets (`DMY`, `MDY`, `YMD` or `UNSPECIFIED`). |
| `currency` | Allowed codes, display symbols, value markers, decimal places and digit grouping. |
| `party_normalization` | How supplier names are normalised, plus explicit supplier aliases. |
| `validation_rules` | A list of rules from the fixed set of rule types below. |
| `matching` | Identity fields and compare fields with tolerances. |
| `pdf_layouts` | Which registered PDF layout parsers this template uses. |
| `summary_fields` | Optional. The fields shown as columns in the Records table. If left out: the first party, identifier and date fields and the last money field. |

Unknown keys are rejected, so a typo in a key name fails loudly instead of being ignored.

## Fields

```json
{ "name": "invoice_number", "label": "Invoice number", "type": "identifier", "required": true,
  "aliases": ["invoice no", "bill no", "document number"] }
```

Field types:

| Type | Normalization | Notes |
| --- | --- | --- |
| `party` | NFKC, case-folded, `&` becomes `and`, punctuation removed, whitespace collapsed, legal suffixes removed, explicit aliases applied | Used for supplier names. |
| `identifier` | Outer whitespace trimmed, inner whitespace removed, upper-cased | Leading zeros and punctuation are kept. `000457` and `457` are different. |
| `date` | See [dates](#dates) | Stored as ISO `YYYY-MM-DD`. |
| `currency` | Upper-cased three-letter code, or a configured marker such as `₹` | |
| `money` | `Decimal`, never float | See [money](#money). |
| `text` | Whitespace collapsed | |

`aliases` are column headings that suggest this field during spreadsheet mapping. Matching is exact after normalising the heading: lower case, `#` read as `no`, `&` as `and`, other punctuation removed. `Invoice #`, `INVOICE NO.` and `invoice_no` all become `invoice no`. Aliases must be unique across fields. There is no fuzzy heading matching; the user confirms every mapping.

## Dates

Every source has one declared date format:

- `DMY` reads `03/04/2025` as 3 April 2025.
- `MDY` reads it as 4 March 2025.
- `YMD` expects the year first.
- `UNSPECIFIED` accepts a numeric date only when it can't be read two ways. `25/03/2025` is accepted; `03/04/2025` is reported as ambiguous.

Always accepted, whatever the format: ISO dates (`2025-03-05`), dates with a month name (`05 Mar 2025`, `March 5, 2025`), and real spreadsheet date cells. Separators `/`, `-` and `.` are all accepted. Two-digit years are rejected. Impossible dates such as `31/02/2025` are rejected with a message.

For spreadsheets the user chooses the format on the mapping screen. The screen shows how many values each format can read, so a register with `03/13/2025` warns that DD/MM/YYYY doesn't fit. For PDFs, each layout declares its format.

## Money

Accepted: an optional currency marker at the start or end (`INR 1,100.00`, `₹500`, `1,200.00 USD`), an optional minus sign or parentheses for negatives, digits with optional comma grouping in groups of 2 or 3 (`12,500.00` and `1,25,000.00`), and a dot as the decimal separator.

Rejected as invalid, never guessed: `12.500,00`, `12 500`, `1,2,3`, `$100` (`$` is not allowed as a marker because it is shared by several currencies).

`currency.minor_units` sets the allowed decimal places per currency; `12.345` in INR is reported. `currency.grouping` can set `indian` digit grouping for display (`₹12,50,000.00`).

## Rule types

Rules are data. Only these types exist; anything else is rejected when the template loads. Every rule has `id`, `label`, `severity` (`error` or `warning`, default `error`) and `applies_to` (default both roles).

| Type | Parameters | What it checks |
| --- | --- | --- |
| `required` | `fields` | Each listed field has a value. |
| `date_valid` | `fields` | Each present date can be read with the source's date format. |
| `money_valid` | `fields`, `allow_negative` | Each present amount parses, is not negative unless allowed, and has no more decimal places than the currency allows. |
| `sum_equals` | `addends`, `total`, `tolerance` | The addends add up to the total within the tolerance. Not checked (and shown as not checked) when a value is missing or invalid. |
| `currency_allowed` | `field` | The currency is a recognised code in `currency.allowed`. |
| `currency_consistency` | `currency_field`, `amount_fields` | Amounts printed with their own currency code use the record's currency. |
| `duplicate_identity` | `fields` | No other active record of the same role has the same normalised values. Usually `applies_to: ["invoice"]`. |

Records with an `error` issue need a note before they can be approved. Warnings don't.

## Matching

```json
"matching": {
  "identity_fields": ["supplier_name", "invoice_number", "currency"],
  "compare": [
    {"field": "invoice_date"},
    {"field": "total_amount", "tolerance": "0.01"}
  ]
}
```

1. A record's identity is its normalised identity fields. A record with a missing or invalid identity field is "Needs correction before matching".
2. A pair is formed only when exactly one active invoice and exactly one free register row share an identity.
3. Two invoices with the same identity are both "Ambiguous" until one is excluded or linked. Two register rows with the same identity make the invoice "Ambiguous" until a reviewer links one. A register row is never used for two invoices.
4. After pairing, each compare field is checked. Money differences up to the tolerance pass and are noted. Anything else is "Mismatched", with a sentence per difference, for example: *Invoice total amount is ₹12,500.00; purchase register total amount is ₹12,050.00 (difference ₹450.00).*
5. If a compare field is missing or invalid on the invoice, the invoice is "Needs correction before matching" and its register row is "Paired invoice needs correction".
6. Amounts never create a match. "Where to look" hints point at rows that agree on everything except the supplier name or currency, but they never pair records.

Tolerances are strings so they stay exact Decimals. Identity and compare fields can't overlap.

## Supplier names

```json
"party_normalization": {
  "legal_suffixes": ["private limited", "pvt ltd", "pvt", "ltd", "llp", "co"],
  "aliases": { "Sablefin Electricals": ["Sablefin Electrical Works"] }
}
```

`Apex Industrial Components Pvt. Ltd.` and `Apex Industrial Components Private Limited` both become `apex industrial components`. Legal suffixes are removed only from the end of the name. Aliases are explicit: each alternative spelling is mapped to the canonical name after the same normalisation. A typo such as `Kestrel Logistic Services` is not matched to `Kestrel Logistics Services`; the reviewer sees a hint instead.

Removing suffixes treats `Alpha Traders Ltd` and `Alpha Traders LLP` as the same supplier. Remove suffixes from the list if a business has legally distinct suppliers that differ only that way.

## PDF layouts

PDF parsing is deterministic code in `backend/app/extraction/invoice_layouts.py`, not configuration. Each layout has a signature and one pattern per field. A field whose pattern doesn't match is left missing, never filled in.

| Layout id | Recognised by | Fields | Dates |
| --- | --- | --- | --- |
| `classic_tax_invoice` | A `TAX INVOICE` line and an `Invoice No:` line | Supplier = first line; `Invoice No:`, `Invoice Date:`, `Currency:`, `Net Amount:`, `Tax Amount (...):`, `Total Amount:` | DD/MM/YYYY |
| `modern_invoice` | First line `INVOICE`, an `Invoice #` line and an `Amount due` line | `From:`, `Invoice #`, `Issued:`, `Subtotal CUR`, `Tax (...) CUR`, `Amount due CUR`; currency from the amount-due line | Month names |
| `billing_statement` | A `BILLING STATEMENT` line and a `Document ref:` line | `Supplier:`, `Document ref:`, `Statement date:`, `Currency:`, `Amount before tax:`, `Tax:`, `Amount payable:` | YYYY-MM-DD |

A PDF that matches no layout is rejected as an unsupported layout. A PDF with no text layer but with images is rejected with "OCR is not supported in this version".

### Adding a layout

1. Add a class to `invoice_layouts.py` with `id`, `name`, `description`, `date_order`, `signature` and `patterns` (copy an existing one).
2. Register it in `extraction/registry.py`.
3. Add its id to `pdf_layouts` in the template.
4. Add a synthetic sample to `sample_data/generate_samples.py` and a test in `backend/tests/test_pdf_extraction.py`.

### Adding a different extractor (for example an LLM)

Implement `DocumentExtractor` from `extraction/base.py`: `can_handle(doc)` and `extract(doc)` returning raw string values with evidence. Set `method` to an honest description (for example "LLM extraction: model X, unverified"). Normalization, validation, matching, review and export don't change. Don't invent confidence scores; keep the factual field statuses.

## Adding a second template

For example an expense-register check:

1. Copy `supplier_invoice.json` to `expense_register.json`, give it a new `id`, and change roles, fields, aliases, rules and matching keys.
2. Set `pdf_layouts` to `[]` if it only takes spreadsheets.
3. Restart the server. The template appears in the New batch dialog. Ingestion, mapping, review, history and export work from the template definition.

`backend/tests/test_second_template.py` does exactly this with an expense-claims template (fields Employee, Claim reference, Date spent, Currency, Amount; EUR only) and runs it through upload, mapping, matching, search, approval and export without code changes. Use it as a starting point.

Current constraints to keep in mind: the two role names are fixed as `invoice` and `reference` (their labels are configurable), and a template needs one currency field if it has money fields.
