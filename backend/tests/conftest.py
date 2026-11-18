from __future__ import annotations

import json
import warnings
from pathlib import Path

import pytest

warnings.filterwarnings("ignore", message=".*httpx.*")

from fastapi.testclient import TestClient  # noqa: E402

from app.main import create_app  # noqa: E402
from app.settings import SAMPLE_DIR  # noqa: E402
from app.template_config import get_template  # noqa: E402
from app.validation import RecordInput  # noqa: E402

FIELDS = ("supplier_name", "invoice_number", "invoice_date", "currency", "net_amount", "tax_amount", "total_amount")


@pytest.fixture
def template():
    return get_template("supplier_invoice")


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    return tmp_path / "data"


@pytest.fixture
def client(data_dir: Path):
    with TestClient(create_app(str(data_dir))) as c:
        yield c


@pytest.fixture(scope="session")
def expected():
    return json.loads((SAMPLE_DIR / "expected_outcomes.json").read_text(encoding="utf-8"))


def make_input(rid: int, role: str = "invoice", supplier: str | None = "Acme Traders", number: str | None = "INV-1",
               date: str | None = "05/03/2025", currency: str | None = "INR", net: str | None = "100.00",
               tax: str | None = "18.00", total: str | None = "118.00", excluded: bool = False,
               order: str = "DMY") -> RecordInput:
    values = dict(zip(FIELDS, (supplier, number, date, currency, net, tax, total)))
    return RecordInput(id=rid, role=role, values=dict(values), original=dict(values), kinds={}, corrected=set(),
                       date_order=order, excluded=excluded, label=f"{role}-{rid}")


def records_by(client: TestClient, batch_id: int) -> list[dict]:
    r = client.get(f"/api/batches/{batch_id}/records")
    assert r.status_code == 200, r.text
    return r.json()


def find(records: list[dict], **criteria) -> dict:
    hits = [r for r in records if all(r.get(k) == v for k, v in criteria.items())]
    assert len(hits) == 1, (criteria, [(r["id"], r["file_name"], r["invoice_number"]) for r in hits])
    return hits[0]
