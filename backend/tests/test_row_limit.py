"""Spreadsheets over the row limit are never imported in part, and the batch says it is incomplete."""

import dataclasses
import io

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook, load_workbook

from app.main import create_app

LIMIT = 5
HEAD = "Supplier,Inv No,Inv Date,Ccy,Net,Tax,Total\n"


def rows(n: int, start: int = 1) -> str:
    return "".join(f"Acme Traders,INV-{i},05/03/2025,INR,100.00,18.00,118.00\n" for i in range(start, start + n))


@pytest.fixture
def client(tmp_path):
    app = create_app(str(tmp_path / "data"))
    app.state.settings = dataclasses.replace(app.state.settings, max_spreadsheet_rows=LIMIT)
    with TestClient(app) as c:
        yield c


def batch(c):
    return c.post("/api/batches", json={"name": "limit", "template_id": "supplier_invoice"}).json()["id"]


def upload(c, b, name, data, role="invoice"):
    return c.post(f"/api/batches/{b}/files", data={"role": role}, files=[("files", (name, data))]).json()[0]


def confirm(c, f, **extra):
    p = c.get(f"/api/files/{f['id']}/preview", params=extra.get("params")).json()
    body = {"mapping": p["proposed_mapping"], "date_order": "DMY", "header_row": p["header_row"], "sheet": p["sheet"]}
    return p, c.post(f"/api/files/{f['id']}/mapping", json=body)


def xlsx(n_rows: int) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.append(["Register (synthetic)"])
    ws.append([])
    ws.append(HEAD.strip().split(","))
    for i in range(1, n_rows + 1):
        ws.append(["Acme Traders", f"INV-{i}", "05/03/2025", "INR", "100.00", "18.00", "118.00"])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def completeness(c, b):
    return c.get(f"/api/batches/{b}").json()["counts"]["completeness"]


@pytest.mark.parametrize("kind", ["csv", "xlsx"])
def test_exactly_at_the_limit_imports_every_row(client, kind):
    b = batch(client)
    data = (HEAD + rows(LIMIT)).encode() if kind == "csv" else xlsx(LIMIT)
    f = upload(client, b, f"ok.{kind}", data)
    p, r = confirm(client, f)
    assert p["over_limit"] is False and p["total_rows"] == LIMIT and p["row_limit"] == LIMIT
    assert r.status_code == 200, r.text
    client.post(f"/api/batches/{b}/process")
    fi = client.get(f"/api/batches/{b}").json()["files"][0]
    assert fi["status"] == "processed" and fi["record_count"] == LIMIT
    assert fi["status_detail"].startswith(f"All {LIMIT} data rows imported")
    assert completeness(client, b) == {"complete": True, "gaps": []}


@pytest.mark.parametrize("kind", ["csv", "xlsx"])
def test_one_row_over_the_limit_is_refused_not_truncated(client, kind):
    b = batch(client)
    data = (HEAD + rows(LIMIT + 1)).encode() if kind == "csv" else xlsx(LIMIT + 1)
    f = upload(client, b, f"big.{kind}", data)
    p, r = confirm(client, f)
    assert p["over_limit"] is True and p["row_limit"] == LIMIT
    assert r.status_code == 400 and f"more than {LIMIT} data rows" in r.json()["detail"]
    client.post(f"/api/batches/{b}/process")
    detail = client.get(f"/api/batches/{b}").json()
    assert detail["files"][0]["status"] == "needs_mapping" and detail["counts"]["invoices"] == 0
    comp = detail["counts"]["completeness"]
    assert comp["complete"] is False and comp["gaps"][0]["file_name"] == f"big.{kind}"


def test_heading_far_down_does_not_hide_extra_rows(client):
    # 40 lines of preamble, the heading on row 41, then one row more than the limit.
    preamble = "".join(f"note line {i}\n" for i in range(1, 41))
    f_data = (preamble + HEAD + rows(LIMIT + 1)).encode()
    b = batch(client)
    f = upload(client, b, "late_heading.csv", f_data)
    p = client.get(f"/api/files/{f['id']}/preview", params={"header_row": 41}).json()
    assert p["header_row"] == 41 and p["over_limit"] is True


def test_rows_far_beyond_the_read_cap_are_detected(client):
    b = batch(client)
    f = upload(client, b, "huge.csv", (HEAD + rows(1200)).encode())  # cap is LIMIT + 1000 + 1 raw rows
    p = client.get(f"/api/files/{f['id']}/preview").json()
    assert p["over_limit"] is True


def test_trailing_blank_rows_do_not_count(client):
    b = batch(client)
    f = upload(client, b, "blanks.csv", (HEAD + rows(LIMIT) + ",,,,,,\n" * 2000).encode())
    p, r = confirm(client, f)
    assert p["over_limit"] is False and r.status_code == 200


def test_processing_rejects_a_file_that_is_over_the_limit_at_import_time(client):
    b = batch(client)
    f = upload(client, b, "grew.csv", (HEAD + rows(LIMIT + 2)).encode())
    app = client.app
    app.state.settings = dataclasses.replace(app.state.settings, max_spreadsheet_rows=LIMIT + 5)
    _, r = confirm(client, f)
    assert r.status_code == 200
    app.state.settings = dataclasses.replace(app.state.settings, max_spreadsheet_rows=LIMIT)  # limit lowered later
    client.post(f"/api/batches/{b}/process")
    fi = client.get(f"/api/batches/{b}").json()["files"][0]
    assert fi["status"] == "rejected" and fi["rejection_code"] == "too_many_rows" and fi["record_count"] == 0
    assert client.get(f"/api/batches/{b}/records").json() == []
    wb = load_workbook(io.BytesIO(client.get(f"/api/batches/{b}/export").content))
    summary = {r[0]: r[1] for r in wb["Summary"].iter_rows(values_only=True)}
    assert summary["Inputs fully imported"].startswith("NO")
    assert any(str(k).startswith("Files not fully imported: grew.csv") for k in summary)


def test_missing_results_say_a_register_file_was_not_imported(client):
    b = batch(client)
    inv = upload(client, b, "invoices.csv", (HEAD + rows(2)).encode())
    reg_ok = upload(client, b, "register_part1.csv", (HEAD + rows(1)).encode(), role="reference")
    reg_big = upload(client, b, "register_part2.csv", (HEAD + rows(LIMIT + 1, start=2)).encode(), role="reference")
    for f in (inv, reg_ok):
        assert confirm(client, f)[1].status_code == 200
    assert confirm(client, reg_big)[1].status_code == 400
    client.post(f"/api/batches/{b}/process")
    recs = {r["invoice_number"]: r for r in client.get(f"/api/batches/{b}/records?role=invoice").json()}
    assert recs["INV-1"]["match_status"] == "matched"
    missing = client.get(f"/api/records/{recs['INV-2']['id']}").json()
    assert missing["match_status"] == "missing_from_reference"
    text = " ".join(missing["match"]["explanation"])
    assert "Not every purchase register file is fully imported (register_part2.csv)" in text
    assert completeness(client, b)["complete"] is False
