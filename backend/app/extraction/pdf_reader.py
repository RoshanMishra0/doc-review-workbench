"""Read the text layer of a PDF with pypdf. No OCR."""

from __future__ import annotations

import logging
from pathlib import Path

from pypdf import PdfReader

from .base import PdfText, UnreadableDocument

log = logging.getLogger(__name__)

MAX_PAGES = 50


def _count_images(page) -> int:
    try:
        resources = page.get("/Resources")
        if resources is None:
            return 0
        resources = resources.get_object()
        xobjects = resources.get("/XObject")
        if xobjects is None:
            return 0
        xobjects = xobjects.get_object()
        count = 0
        for name in xobjects:
            obj = xobjects[name].get_object()
            if obj.get("/Subtype") == "/Image":
                count += 1
        return count
    except Exception:  # noqa: BLE001 - image counting is best-effort evidence only
        return 0


def read_pdf_text(path: Path) -> PdfText:
    with path.open("rb") as fh:
        head = fh.read(1024)
    if b"%PDF-" not in head:
        raise UnreadableDocument(
            "The file does not contain a PDF header, so it is not a readable PDF.", code="not_pdf"
        )
    try:
        reader = PdfReader(str(path), strict=False)
        if reader.is_encrypted:
            try:
                ok = reader.decrypt("")
            except Exception:  # noqa: BLE001
                ok = 0
            if not ok:
                raise UnreadableDocument("The PDF is password-protected. Protected PDFs are not supported.",
                                         code="encrypted")
        page_count = len(reader.pages)
        if page_count == 0:
            raise UnreadableDocument("The PDF has no pages.", code="unreadable")
        if page_count > MAX_PAGES:
            raise UnreadableDocument(
                f"The PDF has {page_count} pages; this version reads invoices of up to {MAX_PAGES} pages.",
                code="too_long",
            )
        pages: list[str] = []
        images = 0
        for page in reader.pages:
            pages.append(page.extract_text() or "")
            images += _count_images(page)
    except UnreadableDocument:
        raise
    except Exception as exc:  # noqa: BLE001 - any parser failure means the file is unreadable
        log.info("PDF could not be parsed (%s)", type(exc).__name__)
        raise UnreadableDocument(
            "The PDF structure could not be read. The file may be damaged or incomplete.", code="damaged"
        ) from exc
    return PdfText(pages=pages, image_count=images)
