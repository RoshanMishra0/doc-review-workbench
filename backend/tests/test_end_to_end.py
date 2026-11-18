"""End-to-end checks with the synthetic dataset against the documented expected outcomes."""

import io

from fastapi.testclient import TestClient
from openpyxl import load_workbook

from app.main import create_app

from .conftest import find, records_by


def test_harbor_lane_outcomes_match_documentation(client, expected):
    r = client.post("/api/samples/harbor_lane/load")
    assert r.status_code == 200
    body = r.json()
    assert body["auto_mapped"] == ["purchase_register.xlsx"] and body["waiting_for_mapping"] == []
    b = body["batch_id"]
    recs = records_by(client, b)
    exp = expected["harbor_lane"]

    invoices = [x for x in recs if x["role"] == "invoice"]
    assert len(invoices) == len(exp["invoices"])
    for name, e in exp["invoices"].items():
        rec = find(invoices, file_name=name)
        assert rec["match_status"] == e["expected_match"], name
        for category in e["expected_issues"]:
            assert category in rec["categories"], (name, category, rec["categories"])

    refs = [x for x in recs if x["role"] == "reference"]
    assert len(refs) == len(exp["register_rows"])
    for e in exp["register_rows"]:
        rec = next(x for x in refs if x["source_ref"].endswith(f"row {e['row']}"))
        assert rec["invoice_number"] == e["invoice_number"]
        assert rec["match_status"] == e["expected_match"], e

    files = {f["original_name"]: f for f in client.get(f"/api/batches/{b}").json()["files"]}
    assert len(files) == 19  # 18 PDFs + the register: every upload is accounted for
    for name, e in exp["rejected_files"].items():
        assert files[name]["status"] == "rejected" and files[name]["rejection_code"] == e["reason"]


def test_acceptance_flow_with_restart(data_dir):
    """Load sample -> inspect source -> correct -> rerun -> approve -> restart -> export."""
    with TestClient(create_app(str(data_dir))) as c:
        b = c.post("/api/samples/harbor_lane/load").json()["batch_id"]
        rec = find(records_by(c, b), file_name="tarnwood_TP-5520.pdf")

        # Inspect the source: page text and per-field evidence are available.
        d = c.get(f"/api/records/{rec['id']}").json()
        assert d["pages"] and "Total Amount: 17,700.00" in d["pages"][0]["text"]
        assert d["extracted"]["total_amount"]["evidence"]["text"] == "Total Amount: 17,700.00"
        assert d["fields"]["tax_amount"]["status"] == "missing"

        # Correct and rerun checks.
        d = c.post(f"/api/records/{rec['id']}/corrections", json={"values": {"tax_amount": "2700.00"}}).json()["record"]
        assert d["validation_status"] == "passed" and d["match_status"] == "matched"

        # Approve.
        assert c.post(f"/api/records/{rec['id']}/approve", json={}).json()["review_status"] == "approved"

    # Restart.
    with TestClient(create_app(str(data_dir))) as c:
        d = c.get(f"/api/records/{rec['id']}").json()
        assert d["review_status"] == "approved" and d["match_status"] == "matched"
        x = c.get(f"/api/batches/{b}/export")
        wb = load_workbook(io.BytesIO(x.content))
        approved = list(wb["Approved"].iter_rows(values_only=True))
        assert len(approved) == 2 and approved[1][0] == rec["id"]


def test_meridian_needs_mapping_and_date_format(client, expected):
    exp = expected["meridian"]
    body = client.post("/api/samples/meridian/load").json()
    assert body["auto_mapped"] == ["supplier_invoice_listing.csv"]
    assert body["waiting_for_mapping"] == ["purchase_register.csv"]
    b = body["batch_id"]
    # Before the register is mapped, nothing is compared.
    assert {r["match_status"] for r in records_by(client, b)} == {"not_compared"}

    files = client.get(f"/api/batches/{b}").json()["files"]
    reg = next(f for f in files if f["role"] == "reference")
    preview = client.get(f"/api/files/{reg['id']}/preview").json()
    da = preview["date_analysis"]
    assert da["MDY"] == da["values"] == 8 and da["DMY"] < da["values"]

    r = client.post(f"/api/files/{reg['id']}/mapping",
                    json={"mapping": exp["register_mapping"], "date_order": exp["register_date_order"],
                          "profile_name": "Meridian purchase register"})
    assert r.status_code == 200, r.text
    client.post(f"/api/batches/{b}/process")
    recs = records_by(client, b)
    invoices = [x for x in recs if x["role"] == "invoice"]
    refs = [x for x in recs if x["role"] == "reference"]
    for e in exp["invoices"]:
        rec = next(x for x in invoices if x["source_ref"].endswith(f"row {e['row']}"))
        assert rec["invoice_number"] == e["invoice_number"]
        assert rec["match_status"] == e["expected_match"], e
        for category in e["expected_issues"]:
            assert category in rec["categories"]
    for e in exp["register_rows"]:
        rec = next(x for x in refs if x["source_ref"].endswith(f"row {e['row']}"))
        assert rec["match_status"] == e["expected_match"], e

    # The register row whose invoice lacks a currency points at that invoice, in plain words.
    rc_ref = next(x for x in refs if x["invoice_number"] == "RC-0098")
    hints = client.get(f"/api/records/{rc_ref['id']}").json()["match"]["hints"]
    assert hints and "currency is missing or invalid" in hints[0] and "None" not in hints[0]
    rc_inv = next(x for x in invoices if x["invoice_number"] == "RC-0098")
    fixed = client.post(f"/api/records/{rc_inv['id']}/corrections", json={"values": {"currency": "INR"}}).json()
    assert fixed["record"]["match_status"] == "matched"

    # A second load reuses the saved mapping automatically.
    again = client.post("/api/samples/meridian/load").json()
    assert sorted(again["auto_mapped"]) == ["purchase_register.csv", "supplier_invoice_listing.csv"]
    assert again["summary"]["match"]["invoice"].get("matched") == 5
