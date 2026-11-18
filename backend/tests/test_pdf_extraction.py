from pathlib import Path

import pytest

from app.extraction.base import UnreadableDocument
from app.extraction.pdf_reader import read_pdf_text
from app.extraction.registry import LayoutRejection, extract_pdf
from app.settings import SAMPLE_DIR

INVOICES = SAMPLE_DIR / "harbor_lane" / "invoices"
LAYOUTS = ["classic_tax_invoice", "modern_invoice", "billing_statement"]


def extract(name: str):
    return extract_pdf(read_pdf_text(INVOICES / name), LAYOUTS)


def values(result):
    return {k: v.value for k, v in result.fields.items()}


def test_classic_layout():
    r = extract("apex_INV-00123.pdf")
    assert r.layout_id == "classic_tax_invoice" and r.date_order == "DMY"
    assert values(r) == {
        "supplier_name": "Apex Industrial Components Pvt. Ltd.", "invoice_number": "INV-00123",
        "invoice_date": "05/03/2025", "currency": "INR", "net_amount": "10,000.00", "tax_amount": "1,800.00",
        "total_amount": "11,800.00"}
    ev = r.fields["total_amount"].evidence
    assert ev.page == 1 and ev.text == "Total Amount: 11,800.00"
    assert "Deterministic text parser" in r.method


def test_modern_layout_keeps_printed_currency_codes():
    r = extract("kestrel_000457.pdf")
    assert r.layout_id == "modern_invoice"
    v = values(r)
    assert v["invoice_number"] == "000457"  # leading zeros preserved
    assert v["invoice_date"] == "12 Mar 2025"
    assert v["currency"] == "INR"
    assert v["total_amount"] == "INR 23,100.00"


def test_statement_layout():
    r = extract("sablefin_SE-2025-118.pdf")
    assert r.layout_id == "billing_statement" and r.date_order == "YMD"
    assert values(r)["invoice_date"] == "2025-03-14"
    assert values(r)["supplier_name"] == "Sablefin Electricals"


def test_missing_field_is_reported_not_invented():
    r = extract("tarnwood_TP-5520.pdf")
    assert r.fields["tax_amount"].value is None
    assert r.fields["tax_amount"].evidence is None
    assert r.fields["total_amount"].value == "17,700.00"


def test_unsupported_layout_is_rejected():
    r = extract("lumenridge_quotation_Q-219.pdf")
    assert isinstance(r, LayoutRejection) and r.code == "unsupported_layout"


def test_image_only_pdf_explains_ocr_is_not_supported():
    r = extract("scan_marlow_MSU-88120.pdf")
    assert isinstance(r, LayoutRejection) and r.code == "image_only"
    assert "OCR is not supported" in r.reason


def test_damaged_pdf():
    with pytest.raises(UnreadableDocument) as exc:
        read_pdf_text(INVOICES / "invoice_damaged.pdf")
    assert exc.value.code == "damaged"


def test_non_pdf_bytes(tmp_path: Path):
    p = tmp_path / "fake.pdf"
    p.write_bytes(b"this is a text file")
    with pytest.raises(UnreadableDocument) as exc:
        read_pdf_text(p)
    assert exc.value.code == "not_pdf"


def test_all_supported_sample_invoices_extract_every_field_but_the_known_gap():
    for pdf in sorted(INVOICES.glob("*.pdf")):
        if pdf.name in {"lumenridge_quotation_Q-219.pdf", "scan_marlow_MSU-88120.pdf", "invoice_damaged.pdf"}:
            continue
        r = extract(pdf.name)
        missing = [k for k, v in r.fields.items() if v.value is None]
        expected_missing = ["tax_amount"] if pdf.name == "tarnwood_TP-5520.pdf" else []
        assert missing == expected_missing, pdf.name
