"""Plain-language labels for statuses and issue categories (shared by API and export)."""

MATCH_STATUS_LABELS = {
    "matched": "Matched",
    "mismatched": "Mismatched",
    "missing_from_reference": "Missing from register",
    "no_invoice": "Register row without uploaded invoice",
    "ambiguous": "Ambiguous match",
    "invalid": "Needs correction before matching",
    "partner_invalid": "Paired invoice needs correction",
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

CATEGORY_LABELS = {
    "missing_required": "Missing required value",
    "invalid_date": "Invalid date",
    "ambiguous_date": "Ambiguous date",
    "invalid_amount": "Invalid amount",
    "arithmetic": "Arithmetic inconsistency",
    "currency": "Currency problem",
    "duplicate": "Possible duplicate",
    "source_note": "Source note",
    "mismatch": "Mismatch with register",
    "missing_from_reference": "Missing from register",
    "no_invoice": "Register row without invoice",
    "ambiguous": "Ambiguous match",
    "needs_correction": "Needs correction before matching",
    "partner_needs_correction": "Paired invoice needs correction",
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


def all_labels() -> dict:
    return {
        "match_status": MATCH_STATUS_LABELS,
        "validation_status": VALIDATION_STATUS_LABELS,
        "review_status": REVIEW_STATUS_LABELS,
        "category": CATEGORY_LABELS,
        "field_status": FIELD_STATUS_LABELS,
        "file_status": FILE_STATUS_LABELS,
    }
