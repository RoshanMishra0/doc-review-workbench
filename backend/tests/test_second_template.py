"""A second, differently shaped template runs through the same ingestion, review and export code."""

import io
import json
import shutil

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from app.main import create_app
from app.settings import TEMPLATE_DIR
from app.template_config import _load_templates

EXPENSE_TEMPLATE = {
    "id": "expense_check",
    "version": 1,
    "name": "Expense claims vs expense register",
    "synthetic_note": "Test template.",
    "roles": {
        "invoice": {"label": "Claim", "plural": "Expense claims", "accepts": ["csv", "xlsx"]},
        "reference": {"label": "Register row", "plural": "Expense register", "accepts": ["csv", "xlsx"]},
    },
    "fields": [
        {"name": "employee", "label": "Employee", "type": "party", "required": True, "aliases": ["staff member"]},
        {"name": "claim_ref", "label": "Claim reference", "type": "identifier", "required": True, "aliases": ["claim no"]},
        {"name": "spent_on", "label": "Date spent", "type": "date", "required": True, "aliases": ["spend date"]},
        {"name": "currency", "label": "Currency", "type": "currency", "required": True, "aliases": ["ccy"]},
        {"name": "amount", "label": "Amount", "type": "money", "required": True, "aliases": ["claimed"]},
    ],
    "dates": {"default_order": "DMY"},
    "currency": {"allowed": ["EUR"], "symbols": {"EUR": "€"}, "markers": {"EUR": "EUR"}, "minor_units": {"EUR": 2}},
    "validation_rules": [
        {"id": "required", "type": "required", "label": "Required", "fields": ["employee", "claim_ref", "spent_on", "currency", "amount"]},
        {"id": "money", "type": "money_valid", "label": "Amounts valid", "fields": ["amount"]},
        {"id": "dupes", "type": "duplicate_identity", "label": "No duplicate claims",
         "fields": ["employee", "claim_ref", "currency"], "applies_to": ["invoice"]},
    ],
    "matching": {"identity_fields": ["employee", "claim_ref", "currency"], "compare": [{"field": "amount", "tolerance": "0"}]},
}


@pytest.fixture
def two_templates(tmp_path, monkeypatch):
    folder = tmp_path / "templates"
    folder.mkdir()
    shutil.copy(TEMPLATE_DIR / "supplier_invoice.json", folder / "supplier_invoice.json")
    (folder / "expense_check.json").write_text(json.dumps(EXPENSE_TEMPLATE), encoding="utf-8")
    monkeypatch.setenv("DRW_TEMPLATE_DIR", str(folder))
    _load_templates.cache_clear()
    yield
    _load_templates.cache_clear()


def test_expense_template_end_to_end(two_templates, tmp_path):
    with TestClient(create_app(str(tmp_path / "data"))) as c:
        meta = c.get("/api/meta").json()
        expense = next(t for t in meta["templates"] if t["id"] == "expense_check")
        assert [x["name"] for x in expense["summary_columns"]] == ["employee", "claim_ref", "spent_on", "amount"]

        b = c.post("/api/batches", json={"name": "Expenses", "template_id": "expense_check"}).json()["id"]
        claims = "Staff member,Claim no,Spend date,Ccy,Claimed\nA. Rao,C-001,03/02/2025,EUR,120.50\nB. Lee,C-002,04/02/2025,EUR,80.00\n"
        register = "Staff member,Claim no,Spend date,Ccy,Claimed\nA. Rao,C-001,03/02/2025,EUR,120.50\nB. Lee,C-002,04/02/2025,EUR,85.00\n"
        for role, name, text in (("invoice", "claims.csv", claims), ("reference", "register.csv", register)):
            f = c.post(f"/api/batches/{b}/files", data={"role": role}, files=[("files", (name, text.encode()))]).json()[0]
            p = c.get(f"/api/files/{f['id']}/preview").json()
            assert all(p["proposed_mapping"].values())  # every heading came from the new template's aliases
            r = c.post(f"/api/files/{f['id']}/mapping", json={"mapping": p["proposed_mapping"], "date_order": "DMY"})
            assert r.status_code == 200, r.text
        c.post(f"/api/batches/{b}/process")

        recs = c.get(f"/api/batches/{b}/records?role=invoice").json()
        by_ref = {r["fields"]["claim_ref"]["display"]: r for r in recs}
        assert by_ref["C-001"]["match_status"] == "matched"
        assert by_ref["C-002"]["match_status"] == "mismatched"
        assert c.get(f"/api/batches/{b}/records?q=lee").json()[0]["fields"]["employee"]["display"] == "B. Lee"

        detail = c.get(f"/api/records/{by_ref['C-002']['id']}").json()
        assert detail["template_id"] == "expense_check" and detail["role_label"] == "Claim"
        assert "Claim amount is €80.00; expense register amount is €85.00" in " ".join(detail["match"]["explanation"])

        # Review and export work unchanged.
        assert c.post(f"/api/records/{by_ref['C-001']['id']}/approve", json={}).status_code == 200
        wb = load_workbook(io.BytesIO(c.get(f"/api/batches/{b}/export").content))
        headers = [cell.value for cell in wb["All records"][1]]
        assert {"Employee", "Claim reference", "Date spent", "Amount"} <= set(headers)
        assert wb["Approved"].max_row == 2
