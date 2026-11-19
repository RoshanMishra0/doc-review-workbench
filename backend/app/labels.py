"""Plain-language labels for statuses and issue categories (shared by API and export).

Labels that name a role are written with placeholders and filled from the
template's role labels, so the invoice template reads "Missing from purchase
register" and the expense template reads "Missing from expense register".
"""

from __future__ import annotations

_MATCH_STATUS = {
    "matched": "Matched",
    "mismatched": "Mismatched",
    "missing_from_reference": "Missing from {ref}",
    "no_invoice": "{Ref_row} without {rec}",
    "ambiguous": "Ambiguous match",
    "invalid": "Needs correction before matching",
    "partner_invalid": "Paired {rec} needs correction",
    "not_compared": "Not compared",
}

VALIDATION_STATUS_LABELS = {
    "passed": "Checks passed",
    "warnings": "Passed with warnings",
    "failed": "Failed checks",
}

REVIEW_STATUS_LABELS = {
    "awaiting_review": "Awaiting review",
    "approved": "Approved",
    "excluded": "Excluded",
}

_CATEGORY = {
    "missing_required": "Missing required value",
    "invalid_date": "Invalid date",
    "ambiguous_date": "Ambiguous date",
    "invalid_amount": "Invalid amount",
    "arithmetic": "Arithmetic inconsistency",
    "currency": "Currency problem",
    "duplicate": "Possible duplicate",
    "source_note": "Source note",
    "mismatch": "Mismatch with {ref}",
    "missing_from_reference": "Missing from {ref}",
    "no_invoice": "{Ref_row} without {rec}",
    "ambiguous": "Ambiguous match",
    "needs_correction": "Needs correction before matching",
    "partner_needs_correction": "Paired {rec} needs correction",
    "not_compared": "Not compared",
    "other": "Other",
}

FIELD_STATUS_LABELS = {
    "extracted": "Extracted",
    "missing": "Missing",
    "user_corrected": "User corrected",
    "source_default": "Source default",
}

FILE_STATUS_LABELS = {
    "uploaded": "Uploaded, not processed",
    "needs_mapping": "Needs column mapping",
    "ready": "Mapping confirmed, not processed",
    "processed": "Processed",
    "rejected": "Rejected",
    "removed": "Removed",
}

_GENERIC_ROLES = {"ref": "reference", "Ref_row": "Reference row", "rec": "record"}


def _fill(table: dict[str, str], words: dict[str, str]) -> dict[str, str]:
    return {k: v.format(**words) for k, v in table.items()}


def _words(template) -> dict[str, str]:
    if template is None:
        return _GENERIC_ROLES
    ref_row = template.roles["reference"].label
    return {
        "ref": template.roles["reference"].plural.lower(),
        "Ref_row": ref_row[:1].upper() + ref_row[1:],
        "rec": template.roles["invoice"].label.lower(),
    }


def labels_for(template=None) -> dict:
    words = _words(template)
    return {
        "match_status": _fill(_MATCH_STATUS, words),
        "validation_status": VALIDATION_STATUS_LABELS,
        "review_status": REVIEW_STATUS_LABELS,
        "category": _fill(_CATEGORY, words),
        "field_status": FIELD_STATUS_LABELS,
        "file_status": FILE_STATUS_LABELS,
    }


def all_labels() -> dict:
    """Role-neutral labels, for places that are not tied to one template."""
    return labels_for(None)
