"""The shipped expense-claims template, end to end with its synthetic sample."""

import io

from openpyxl import load_workbook


def load(client):
    r = client.post("/api/samples/brightwater_expenses/load")
    assert r.status_code == 200, r.text
    body = r.json()
    assert sorted(body["auto_mapped"]) == ["expense_claims_export.csv", "expense_register.xlsx"]
    assert body["waiting_for_mapping"] == []
    return body["batch_id"]


def by_row(records, role, row):
    return next(r for r in records if r["role"] == role and r["source_ref"].endswith(f"row {row}"))


def claim(client, b, ref, nth=0):
    recs = [r for r in client.get(f"/api/batches/{b}/records?role=invoice").json()
            if r["fields"]["claim_ref"]["display"] == ref]
    return recs[nth]


def test_template_is_selectable(client):
    meta = client.get("/api/meta").json()
    t = next(x for x in meta["templates"] if x["id"] == "expense_claims")
    assert t["roles"]["invoice"]["plural"] == "Expense claims" and t["pdf_layouts"] == []
    assert t["labels"]["match_status"]["missing_from_reference"] == "Missing from expense register"
    r = client.post("/api/batches", json={"name": "My expenses", "template_id": "expense_claims"})
    assert r.status_code == 201 and r.json()["template_name"] == "Expense claims vs expense register"


def test_sample_outcomes_match_documentation(client, expected):
    b = load(client)
    exp = expected["brightwater_expenses"]
    recs = client.get(f"/api/batches/{b}/records").json()
    assert sum(r["role"] == "invoice" for r in recs) == len(exp["claims"]) == 12
    for e in exp["claims"]:
        rec = by_row(recs, "invoice", e["row"])
        assert rec["fields"]["claim_ref"]["display"] == e["claim_ref"]
        assert rec["match_status"] == e["expected_match"], e
        assert set(e["expected_issues"]) <= set(rec["categories"]), (e, rec["categories"])
    for e in exp["register_rows"]:
        rec = by_row(recs, "reference", e["row"])
        assert rec["match_status"] == e["expected_match"], e
    assert client.get(f"/api/batches/{b}").json()["counts"]["completeness"]["complete"] is True


def test_explanations_use_the_templates_words(client):
    b = load(client)
    cat = client.get(f"/api/records/{claim(client, b, 'EXP-1009')['id']}").json()
    assert "Category differs: 'Meals' on the claim, 'Entertainment' in the expense register." in cat["match"]["explanation"]
    amt = client.get(f"/api/records/{claim(client, b, 'EXP-1004')['id']}").json()
    assert "Claim amount is £84.00; expense register amount is £80.00 (difference £4.00)." in amt["match"]["explanation"]
    cur = client.get(f"/api/records/{claim(client, b, 'EXP-1008')['id']}").json()
    assert cur["match"]["hints"] and "currency 'GBP'" in cur["match"]["hints"][0]


def test_demo_review_actions(client):
    b = load(client)
    r = client.post(f"/api/records/{claim(client, b, 'EXP-1005')['id']}/corrections", json={"values": {"amount": "22.50"}})
    assert r.json()["record"]["match_status"] == "matched"
    r = client.post(f"/api/records/{claim(client, b, 'EXP-1006')['id']}/corrections",
                    json={"values": {"expense_date": "20/02/2025"}})
    assert r.json()["record"]["match_status"] == "matched"
    dup = claim(client, b, "EXP-1007", nth=1)
    client.post(f"/api/records/{dup['id']}/exclude", json={"reason": "Submitted twice"})
    assert claim(client, b, "EXP-1007")["match_status"] == "matched"
    soft = client.get(f"/api/records/{claim(client, b, 'EXP-1011')['id']}").json()
    first_row = soft["candidates"][0]["id"]
    r = client.post(f"/api/records/{soft['id']}/link", json={"reference_id": first_row})
    assert r.json()["match_status"] == "matched"
    other = next(c["id"] for c in soft["candidates"] if c["id"] != first_row)
    assert client.get(f"/api/records/{other}").json()["match_status"] == "no_invoice"


def test_export_uses_template_fields_and_labels(client):
    b = load(client)
    wb = load_workbook(io.BytesIO(client.get(f"/api/batches/{b}/export").content))
    assert "Unmatched register rows" in wb.sheetnames
    ws = wb["All records"]
    headers = [c.value for c in ws[1]]
    for h in ("Employee", "Claim reference", "Expense date", "Category", "Currency", "Amount"):
        assert h in headers
    statuses = {row[headers.index("Match status")] for row in ws.iter_rows(min_row=2, values_only=True)}
    assert {"Matched", "Missing from expense register", "Register row without claim"} <= statuses
    summary = {r[0]: r[1] for r in wb["Summary"].iter_rows(values_only=True)}
    assert summary["Expense claims"] == 12 and summary["Inputs fully imported"] == "Yes"
