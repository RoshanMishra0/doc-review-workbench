"""Deterministic text parsers for the documented synthetic invoice layouts.

These are rule-based parsers, not AI. Each layout has a signature (text that
must appear) and one pattern per field. A field whose pattern does not match
is reported as missing; nothing is inferred or filled in.

Supported layouts (see docs/TEMPLATE_GUIDE.md for samples):

* ``classic_tax_invoice`` - supplier name on the first line, a ``TAX INVOICE``
  heading, ``Invoice No:``/``Invoice Date:``/``Currency:`` lines and
  ``Net Amount:``/``Tax Amount ...:``/``Total Amount:`` lines. Dates DD/MM/YYYY.
* ``modern_invoice`` - an ``INVOICE`` heading on the first line, ``From:``,
  ``Invoice #``, ``Issued:`` and ``Subtotal``/``Tax ...``/``Amount due`` lines,
  each amount prefixed by a currency code. Dates with month names.
* ``billing_statement`` - a ``BILLING STATEMENT`` heading and labelled lines
  ``Supplier:``, ``Document ref:``, ``Statement date:`` (YYYY-MM-DD),
  ``Currency:``, ``Amount before tax:``, ``Tax:``, ``Amount payable:``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .base import Evidence, ExtractedField, ExtractionResult, PdfText

FIELDS = ("supplier_name", "invoice_number", "invoice_date", "currency", "net_amount", "tax_amount", "total_amount")


@dataclass
class FieldPattern:
    field: str
    pattern: re.Pattern[str]
    group: str = "v"


def _find(lines: list[tuple[int, int, str]], pattern: re.Pattern[str], group: str = "v"):
    for page, line_no, text in lines:
        m = pattern.search(text)
        if m:
            value = m.group(group)
            value = value.strip() if value else None
            if value:
                return value, Evidence(page=page, line=line_no, text=text)
    return None, None


class _PatternLayout:
    id = ""
    name = ""
    description = ""
    date_order = "DMY"
    signature: tuple[re.Pattern[str], ...] = ()
    patterns: tuple[FieldPattern, ...] = ()

    def can_handle(self, doc: PdfText) -> bool:
        text = "\n".join(t for _, _, t in doc.lines())
        return all(sig.search(text) for sig in self.signature)

    def _supplier(self, lines):  # overridden where the supplier is positional
        return None, None

    def extract(self, doc: PdfText) -> ExtractionResult:
        lines = doc.lines()
        fields: dict[str, ExtractedField] = {}
        for fp in self.patterns:
            value, ev = _find(lines, fp.pattern, fp.group)
            fields[fp.field] = ExtractedField(value=value, kind="text", evidence=ev)
        if "supplier_name" not in fields:
            value, ev = self._supplier(lines)
            fields["supplier_name"] = ExtractedField(value=value, kind="text", evidence=ev)
        for name in FIELDS:
            fields.setdefault(name, ExtractedField(value=None))
        notes = []
        self.post_process(lines, fields, notes)
        pages = [f.evidence.page for f in fields.values() if f.evidence and f.evidence.page]
        return ExtractionResult(
            fields=fields,
            method=f"Deterministic text parser: {self.name} layout",
            layout_id=self.id,
            date_order=self.date_order,
            notes=notes,
            source_page=min(pages) if pages else 1,
        )

    def post_process(self, lines, fields: dict[str, ExtractedField], notes: list[str]) -> None:
        return None


AMOUNT = r"(?P<v>[-(]?\s*[0-9][0-9,]*(?:\.[0-9]+)?\)?)"


class ClassicTaxInvoice(_PatternLayout):
    id = "classic_tax_invoice"
    name = "Classic tax invoice"
    description = "Supplier name on the first line, a TAX INVOICE heading, labelled number/date/currency lines."
    date_order = "DMY"
    signature = (re.compile(r"^TAX INVOICE$", re.M), re.compile(r"^Invoice No:", re.M))
    patterns = (
        FieldPattern("invoice_number", re.compile(r"^Invoice No:\s*(?P<v>\S.*)$")),
        FieldPattern("invoice_date", re.compile(r"^Invoice Date:\s*(?P<v>\S.*)$")),
        FieldPattern("currency", re.compile(r"^Currency:\s*(?P<v>\S+)")),
        FieldPattern("net_amount", re.compile(r"^Net Amount:\s*" + AMOUNT + r"\s*$")),
        FieldPattern("tax_amount", re.compile(r"^Tax Amount(?:\s*\([^)]*\))?:\s*" + AMOUNT + r"\s*$")),
        FieldPattern("total_amount", re.compile(r"^Total Amount:\s*" + AMOUNT + r"\s*$")),
    )

    def _supplier(self, lines):
        # The supplier is the first line of page 1, above the TAX INVOICE heading.
        page_one = [entry for entry in lines if entry[0] == 1]
        for idx, (page, line_no, text) in enumerate(page_one):
            if text == "TAX INVOICE":
                break
            if idx == 0:
                return text, Evidence(page=page, line=line_no, text=text)
        return None, None


class ModernInvoice(_PatternLayout):
    id = "modern_invoice"
    name = "Modern invoice"
    description = "INVOICE heading, From:/Invoice #/Issued: lines, amounts prefixed with a currency code."
    date_order = "DMY"
    signature = (re.compile(r"\AINVOICE$", re.M), re.compile(r"^Amount due\b", re.M),
                 re.compile(r"^Invoice #", re.M))
    patterns = (
        FieldPattern("supplier_name", re.compile(r"^From:\s*(?P<v>\S.*)$")),
        FieldPattern("invoice_number", re.compile(r"^Invoice #\s*(?P<v>\S+)")),
        FieldPattern("invoice_date", re.compile(r"^Issued:\s*(?P<v>\S.*)$")),
        FieldPattern("net_amount", re.compile(r"^Subtotal\s+(?:[A-Z]{3}\s+)?" + AMOUNT + r"\s*$")),
        FieldPattern("tax_amount", re.compile(r"^Tax(?:\s*\([^)]*\))?\s+(?:[A-Z]{3}\s+)?" + AMOUNT + r"\s*$")),
        FieldPattern("total_amount", re.compile(r"^Amount due\s+(?:[A-Z]{3}\s+)?" + AMOUNT + r"\s*$")),
        FieldPattern("currency", re.compile(r"^Amount due\s+(?P<v>[A-Z]{3})\s")),
    )

    def post_process(self, lines, fields, notes):
        # Keep the currency code printed next to each amount so the currency
        # consistency rule can compare it with the record currency.
        code_patterns = {
            "net_amount": re.compile(r"^Subtotal\s+(?P<c>[A-Z]{3})\s"),
            "tax_amount": re.compile(r"^Tax(?:\s*\([^)]*\))?\s+(?P<c>[A-Z]{3})\s"),
        }
        for name, pattern in code_patterns.items():
            f = fields.get(name)
            if f and f.value and f.evidence and f.evidence.text:
                m = pattern.search(f.evidence.text)
                if m:
                    f.value = f"{m['c']} {f.value}"
        total = fields.get("total_amount")
        if total and total.value and fields.get("currency") and fields["currency"].value:
            total.value = f"{fields['currency'].value} {total.value}"
        # The currency's evidence is the "Amount due" line it was read from.


class BillingStatement(_PatternLayout):
    id = "billing_statement"
    name = "Billing statement"
    description = "BILLING STATEMENT heading with labelled lines; dates YYYY-MM-DD."
    date_order = "YMD"
    signature = (re.compile(r"^BILLING STATEMENT$", re.M), re.compile(r"^Document ref:", re.M))
    patterns = (
        FieldPattern("supplier_name", re.compile(r"^Supplier:\s*(?P<v>\S.*)$")),
        FieldPattern("invoice_number", re.compile(r"^Document ref:\s*(?P<v>\S+)")),
        FieldPattern("invoice_date", re.compile(r"^Statement date:\s*(?P<v>\S.*)$")),
        FieldPattern("currency", re.compile(r"^Currency:\s*(?P<v>\S+)")),
        FieldPattern("net_amount", re.compile(r"^Amount before tax:\s*" + AMOUNT + r"\s*$")),
        FieldPattern("tax_amount", re.compile(r"^Tax:\s*" + AMOUNT + r"\s*$")),
        FieldPattern("total_amount", re.compile(r"^Amount payable:\s*" + AMOUNT + r"\s*$")),
    )
