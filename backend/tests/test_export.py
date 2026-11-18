import io
from datetime import datetime
from decimal import Decimal

from openpyxl import load_workbook

from .conftest import find, records_by
from .test_ingestion import confirm, new_batch, upload


def workbook(client, batch_id):
    r = client.get(f"/api/batches/{batch_id}/export")
    assert r.status_code == 200, r.text
    assert "attachment" in r.headers["content-disposition"]
    return load_workbook(io.BytesIO(r.content))


def sheet_dicts(ws):
    rows = list(ws.iter_rows(values_only=True))
    headers = rows[0]
    return [dict(zip(headers, r)) for r in rows[1:]]


def test_formula_like_text_is_never_a_formula(client):
    csv_text = (
        "Supplier,Inv No,Inv Date,Ccy,Net,Tax,Total\n"
        '"=HYPERLINK(""http://example.invalid"",""click"")",+100,05/03/2025,INR,100.00,18.00,118.00\n'
        "@SUM(A1),-200,05/03/2025,INR,\"1,000.00\",180.00,\"1,180.00\"\n"
    )
    b = new_batch(client)
    f = upload(client, b, "invoice", "listing.csv", csv_text.encode())
    p = client.get(f"/api/files/{f['id']}/preview").json()
    assert confirm(client, f["id"], p["proposed_mapping"]).status_code == 200
    client.post(f"/api/batches/{b}/process")
    wb = workbook(client, b)
    ws = wb["All records"]
    headers = [c.value for c in ws[1]]
    col_supplier = headers.index("Supplier name") + 1
    col_number = headers.index("Invoice number") + 1
    col_total = headers.index("Total amount") + 1
    for row in range(2, ws.max_row + 1):
        for col in (col_supplier, col_number):
            cell = ws.cell(row, col)
            assert cell.data_type == "s", (cell.coordinate, cell.value)
            assert cell.value.startswith("'"), cell.value
        total = ws.cell(row, col_total)
        assert total.data_type == "n" and isinstance(total.value, (int, float))
    # No cell anywhere in the workbook is a formula.
    for sheet in wb.worksheets:
        for row in sheet.iter_rows():
            for cell in row:
                assert cell.data_type != "f", (sheet.title, cell.coordinate)


def test_export_matches_the_reviewed_state(client):
    b = client.post("/api/samples/harbor_lane/load").json()["batch_id"]
    recs = records_by(client, b)
    tarnwood = find(recs, file_name="tarnwood_TP-5520.pdf")
    client.post(f"/api/records/{tarnwood['id']}/corrections", json={"values": {"tax_amount": "2,700.00"}})
    client.post(f"/api/records/{tarnwood['id']}/approve", json={})
    copy = find(recs, file_name="quillmark_QS-0091_resent.pdf")
    client.post(f"/api/records/{copy['id']}/exclude", json={"reason": "Duplicate copy"})

    wb = workbook(client, b)
    assert wb.sheetnames == ["Summary", "All records", "Approved", "Outstanding exceptions",
                             "Unmatched register rows", "Rejected files", "Review history"]
    api_records = {r["id"]: r for r in records_by(client, b)}
    all_rows = sheet_dicts(wb["All records"])
    assert len(all_rows) == len(api_records)
    for row in all_rows:
        api = api_records[row["Record ID"]]
        assert row["Source reference"] == api["source_ref"]
        assert row["Review status"].lower().replace(" ", "_") == api["review_status"]
        if api["invoice_number"] is not None:
            assert str(row["Invoice number"]).lstrip("'") == api["invoice_number"]

    t = next(r for r in all_rows if r["Record ID"] == tarnwood["id"])
    assert t["Tax amount"] == 2700 and isinstance(t["Tax amount"], (int, float))
    assert Decimal(str(t["Total amount"])) == Decimal("17700")
    assert isinstance(t["Invoice date"], datetime) and t["Invoice date"].date().isoformat() == "2025-03-11"
    assert t["Corrected fields"] == "Tax amount"
    assert t["Match status"] == "Matched" and t["Review status"] == "Approved"
    assert t["Matched source reference"].startswith("purchase_register.xlsx")

    approved = sheet_dicts(wb["Approved"])
    assert [r["Record ID"] for r in approved] == [tarnwood["id"]]

    exceptions = sheet_dicts(wb["Outstanding exceptions"])
    ids_with_exceptions = {r["Record ID"] for r in exceptions}
    assert tarnwood["id"] not in ids_with_exceptions  # approved
    assert copy["id"] not in ids_with_exceptions  # excluded
    assert find(recs, file_name="apex_INV-00131.pdf")["id"] in ids_with_exceptions

    unmatched = {r["Invoice number"] for r in sheet_dicts(wb["Unmatched register rows"])}
    assert {"000463", "MSU-88120", "TP-5531"} <= unmatched
    assert "INV-00123" not in unmatched

    rejected = {r["File name"]: r for r in sheet_dicts(wb["Rejected files"])}
    assert set(rejected) == {"lumenridge_quotation_Q-219.pdf", "scan_marlow_MSU-88120.pdf", "invoice_damaged.pdf"}
    assert "OCR is not supported" in rejected["scan_marlow_MSU-88120.pdf"]["Reason"]

    history = sheet_dicts(wb["Review history"])
    corrected = [h for h in history if h["Action"] == "corrected"]
    assert corrected and corrected[0]["Field"] == "Tax amount" and corrected[0]["New value"] == "2,700.00"
    assert any(h["Action"] == "excluded" and h["Note"] == "Duplicate copy" for h in history)
