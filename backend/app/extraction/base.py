"""Extraction interfaces.

An extractor turns one source document into raw field values plus the
evidence a reviewer needs to check them. Extractors never fill in values
they did not find: a missing field stays ``None``.

To add another parser (or a future LLM-based extractor), implement
``DocumentExtractor`` and register it in ``registry.py``. The rest of the
pipeline (normalization, validation, matching, review, export) does not
change. Any such extractor must label its method honestly in ``method``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class Evidence:
    """Where a value came from, so a reviewer can check it."""

    page: int | None = None  # 1-based page for documents
    line: int | None = None  # 1-based line within the page text
    text: str | None = None  # the source line or cell text
    cell: str | None = None  # spreadsheet cell reference, e.g. "Register!B14"
    column: str | None = None  # spreadsheet column heading

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if v is not None}


@dataclass
class ExtractedField:
    value: str | None
    kind: str = "text"  # text | number | date_cell | source_default
    evidence: Evidence | None = None

    def to_dict(self) -> dict:
        return {
            "value": self.value,
            "kind": self.kind,
            "evidence": self.evidence.to_dict() if self.evidence else None,
        }


@dataclass
class ExtractionResult:
    fields: dict[str, ExtractedField]
    method: str  # factual description, e.g. "Deterministic text parser: Classic tax invoice layout"
    layout_id: str | None = None
    date_order: str = "DMY"
    notes: list[str] = field(default_factory=list)
    source_page: int | None = None


@dataclass
class PdfText:
    pages: list[str]
    image_count: int = 0

    @property
    def has_text(self) -> bool:
        return any(p.strip() for p in self.pages)

    def lines(self) -> list[tuple[int, int, str]]:
        """(page, line, text) for every non-empty line, 1-based."""
        out: list[tuple[int, int, str]] = []
        for page_no, page in enumerate(self.pages, start=1):
            for line_no, raw in enumerate(page.splitlines(), start=1):
                text = " ".join(raw.split())
                if text:
                    out.append((page_no, line_no, text))
        return out


class UnreadableDocument(Exception):
    """The file could not be read at all. ``reason`` is shown to the user."""

    def __init__(self, reason: str, code: str = "unreadable"):
        super().__init__(reason)
        self.reason = reason
        self.code = code


class DocumentExtractor(Protocol):
    id: str
    name: str
    description: str
    date_order: str

    def can_handle(self, doc: PdfText) -> bool: ...

    def extract(self, doc: PdfText) -> ExtractionResult: ...
