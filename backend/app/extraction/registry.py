"""Registered document extractors and layout selection."""

from __future__ import annotations

from dataclasses import dataclass

from .base import DocumentExtractor, ExtractionResult, PdfText
from .invoice_layouts import BillingStatement, ClassicTaxInvoice, ModernInvoice

PDF_EXTRACTORS: dict[str, DocumentExtractor] = {
    e.id: e for e in (ClassicTaxInvoice(), ModernInvoice(), BillingStatement())
}


@dataclass
class LayoutRejection:
    code: str  # image_only | no_text | unsupported_layout | ambiguous_layout
    reason: str


def extract_pdf(doc: PdfText, enabled: list[str]) -> ExtractionResult | LayoutRejection:
    if not doc.has_text:
        if doc.image_count:
            return LayoutRejection(
                "image_only",
                "This PDF contains only images (for example a scan) and no text layer. "
                "OCR is not supported in this version, so no values were read.",
            )
        return LayoutRejection("no_text", "The PDF has no readable text.")
    candidates = [PDF_EXTRACTORS[i] for i in enabled if i in PDF_EXTRACTORS and PDF_EXTRACTORS[i].can_handle(doc)]
    if not candidates:
        names = ", ".join(PDF_EXTRACTORS[i].name for i in enabled if i in PDF_EXTRACTORS)
        return LayoutRejection(
            "unsupported_layout",
            f"The text is readable but does not match a supported invoice layout ({names}).",
        )
    if len(candidates) > 1:
        return LayoutRejection(
            "ambiguous_layout",
            "The text matches more than one supported layout (" + ", ".join(c.name for c in candidates) + ").",
        )
    return candidates[0].extract(doc)
