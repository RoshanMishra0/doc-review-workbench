import io
from decimal import Decimal

from openpyxl import Workbook

from .conftest import find, records_by


def new_batch(client, name="Test batch"):
    r = client.post("/api/batches", json={"name": name, "template_id": "supplier_invoice"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def upload(client, batch_id, role, name, data, content_type="application/octet-stream"):
    r = client.post(f"/api/batches/{batch_id}/files", data={"role": role},
                    files=[("files", (name, data, content_type))])
    assert r.status_code == 201, r.text
    return r.json()[0]


def confirm(client, file_id, mapping, date_order="DMY", default_currency=None, profile_name=None, **extra):
    body = {"mapping": mapping, "date_order": date_order, "default_currency": default_currency,
            "profile_name": profile_name, **extra}
    return client.post(f"/api/files/{file_id}/mapping", json=body)


def xlsx_bytes(rows, sheet="Sheet1", extra_sheets=()):
    wb = Workbook()
    for name in extra_sheets:
        wb.create_sheet(name)["A1"] = "notes only"
    ws = wb.active
    ws.title = sheet
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


LISTING_A = ("Vendor Name,Bill No.,Bill Date,Currency,Taxable Value,GST Amount,Bill Total\n"
             "Acme Traders,000123,05/03/2025,INR,\"1,000.00\",180.00,\"1,180.00\"\n")
LISTING_B = ("Party,Supplier Invoice Ref,Supplier Invoice Date,Curr.,Basic Value,Tax Value,Doc Total\n"
             "Acme Traders,000123,03/05/2025,INR,1000.00,180.00,1180.00\n")


def test_different_headings_map_to_the_same_fields(client):
    b = new_batch(client)
    a = upload(client, b, "invoice", "a.csv", LISTING_A.encode())
    p = client.get(f"/api/files/{a['id']}/preview").json()
    assert p["proposed_mapping"] == {
        "supplier_name": "Vendor Name", "invoice_number": "Bill No.", "invoice_date": "Bill Date",
        "currency": "Currency", "net_amount": "Taxable Value", "tax_amount": "GST Amount", "total_amount": "Bill Total"}

    reg = upload(client, b, "reference", "b.csv", LISTING_B.encode())
    p2 = client.get(f"/api/files/{reg['id']}/preview").json()
    assert p2["proposed_mapping"]["supplier_name"] is None  # "Party" is not an alias
    assert p2["proposed_mapping"]["total_amount"] is None  # "Doc Total" is not an alias
    assert p2["proposed_mapping"]["net_amount"] == "Basic Value"

    # Incomplete mapping is refused with a clear message.
    bad = confirm(client, reg["id"], p2["proposed_mapping"])
    assert bad.status_code == 400 and "Supplier name" in bad.json()["detail"]

    mapping = dict(p2["proposed_mapping"], supplier_name="Party", total_amount="Doc Total")
    ok = confirm(client, reg["id"], mapping, date_order="MDY", profile_name="Business B register")
    assert ok.status_code == 200, ok.text
    assert confirm(client, a["id"], p["proposed_mapping"]).status_code == 200

    client.post(f"/api/batches/{b}/process")
    recs = records_by(client, b)
    inv = find(recs, role="invoice")
    ref = find(recs, role="reference")
    assert inv["match_status"] == "matched" and inv["partner_id"] == ref["id"]
    assert inv["invoice_number"] == "000123"  # leading zeros preserved from CSV
    assert inv["invoice_date"] == ref["invoice_date"] == "05 Mar 2025"


def test_saved_mapping_is_reused_for_the_same_headings(client):
    b = new_batch(client)
    first = upload(client, b, "reference", "reg1.csv", LISTING_B.encode())
    p = client.get(f"/api/files/{first['id']}/preview").json()
    mapping = dict(p["proposed_mapping"], supplier_name="Party", total_amount="Doc Total")
    assert confirm(client, first["id"], mapping, date_order="MDY", profile_name="Reg B").status_code == 200

    b2 = new_batch(client, "Second batch")
    second = upload(client, b2, "reference", "reg2.csv", LISTING_B.encode())
    p2 = client.get(f"/api/files/{second['id']}/preview").json()
    assert p2["proposed_from"] == "saved mapping 'Reg B'"
    assert p2["proposed_mapping"]["supplier_name"] == "Party"
    assert p2["date_order"] == "MDY"
    profiles = client.get("/api/mapping-profiles").json()
    assert [x["name"] for x in profiles] == ["Reg B"]


def test_mapping_can_be_corrected_by_the_user(client):
    b = new_batch(client)
    f = upload(client, b, "invoice", "a.csv", LISTING_A.encode())
    # Swap net and tax deliberately: the user's mapping wins over the suggestion.
    p = client.get(f"/api/files/{f['id']}/preview").json()
    mapping = dict(p["proposed_mapping"], net_amount="GST Amount", tax_amount="Taxable Value")
    assert confirm(client, f["id"], mapping).status_code == 200
    client.post(f"/api/batches/{b}/process")
    rec = client.get(f"/api/records/{records_by(client, b)[0]['id']}").json()
    assert rec["fields"]["net_amount"]["normalized"] == "180.00"


def test_column_cannot_feed_two_fields(client):
    b = new_batch(client)
    f = upload(client, b, "invoice", "a.csv", LISTING_A.encode())
    p = client.get(f"/api/files/{f['id']}/preview").json()
    mapping = dict(p["proposed_mapping"], tax_amount="Taxable Value")
    r = confirm(client, f["id"], mapping)
    assert r.status_code == 400 and "mapped to both" in r.json()["detail"]


def test_default_currency_is_visible_and_marked(client):
    csv_text = "Supplier,Inv No,Inv Date,Net,Tax,Total\nAcme Traders,9,05/03/2025,100.00,18.00,118.00\n"
    b = new_batch(client)
    f = upload(client, b, "invoice", "nocurrency.csv", csv_text.encode())
    p = client.get(f"/api/files/{f['id']}/preview").json()
    assert p["proposed_mapping"]["currency"] is None
    assert confirm(client, f["id"], p["proposed_mapping"]).status_code == 400  # no currency, no default
    assert confirm(client, f["id"], p["proposed_mapping"], default_currency="INR").status_code == 200
    client.post(f"/api/batches/{b}/process")
    rec = client.get(f"/api/records/{records_by(client, b)[0]['id']}").json()
    assert rec["fields"]["currency"]["status"] == "source_default"
    assert rec["fields"]["currency"]["normalized"] == "INR"


def test_xlsx_sheet_selection_header_row_and_identifiers(client):
    rows = [
        ["Purchase register (synthetic)"],
        [],
        ["Vendor Name", "Bill No.", "Bill Date", "Currency", "Taxable Value", "GST Amount", "Bill Total"],
        ["Acme Traders", "000457", None, "INR", Decimal("1000.00"), Decimal("180.00"), Decimal("1180.00")],
        ["Acme Traders", 458, None, "INR", 1838.1399999999999, 0, 1838.14],
    ]
    from datetime import date
    rows[3][2] = date(2025, 3, 12)
    rows[4][2] = date(2025, 3, 13)
    data = xlsx_bytes(rows, sheet="Register", extra_sheets=())
    # Put a notes sheet first so the register is not the first sheet.
    from openpyxl import load_workbook
    wb = load_workbook(io.BytesIO(data))
    wb.create_sheet("Read me", 0)["A1"] = "This workbook is synthetic."
    buf = io.BytesIO()
    wb.save(buf)

    b = new_batch(client)
    f = upload(client, b, "reference", "reg.xlsx", buf.getvalue())
    p = client.get(f"/api/files/{f['id']}/preview").json()
    assert p["sheets"] == ["Read me", "Register"]
    assert p["sheet"] == "Register"  # chosen because its headings match the aliases
    assert p["header_row"] == 3
    assert p["date_analysis"]["date_cells"] == 2
    assert confirm(client, f["id"], p["proposed_mapping"], sheet="Register", header_row=3).status_code == 200
    client.post(f"/api/batches/{b}/process")
    recs = records_by(client, b)
    text_id = find(recs, invoice_number="000457")
    num_id = find(recs, invoice_number="458")
    assert text_id["invoice_date"] == "12 Mar 2025"
    detail = client.get(f"/api/records/{num_id['id']}").json()
    assert any("leading zeros" in n for n in detail["notes"])
    # Binary float noise in the spreadsheet is not carried into the amount.
    assert detail["fields"]["net_amount"]["normalized"] == "1838.14"
    assert detail["extracted"]["invoice_number"]["evidence"]["cell"] == "Register!B5"


def test_rejected_uploads_are_still_accounted_for(client):
    b = new_batch(client)
    bad_type = upload(client, b, "invoice", "notes.txt", b"hello")
    assert bad_type["status"] == "rejected" and "not supported" in bad_type["status_detail"]
    xls = upload(client, b, "invoice", "old.xls", b"\xd0\xcf\x11\xe0junk")
    assert xls["status"] == "rejected" and ".xlsx" in xls["status_detail"]
    pdf_as_register = upload(client, b, "reference", "reg.pdf", b"%PDF-1.4 junk")
    assert pdf_as_register["status"] == "rejected"
    fake_xlsx = upload(client, b, "reference", "fake.xlsx", b"not a zip")
    assert fake_xlsx["status"] == "rejected"
    empty = upload(client, b, "invoice", "empty.csv", b"")
    assert empty["status"] == "rejected"
    files = client.get(f"/api/batches/{b}").json()["files"]
    assert len(files) == 5 and all(f["status"] == "rejected" for f in files)


def test_upload_name_is_sanitised_and_stored_under_generated_path(client, data_dir):
    b = new_batch(client)
    f = upload(client, b, "invoice", "..\\..\\evil.csv", LISTING_A.encode())
    assert f["original_name"] == "evil.csv"
    stored = list((data_dir / "uploads" / f"batch_{b}").iterdir())
    assert len(stored) == 1 and stored[0].name != "evil.csv" and stored[0].suffix == ".csv"
    assert "stored_name" not in f
