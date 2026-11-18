import hashlib

from fastapi.testclient import TestClient

from app.main import create_app
from app.settings import SAMPLE_DIR

from .conftest import find, records_by


def load_harbor(client):
    r = client.post("/api/samples/harbor_lane/load")
    assert r.status_code == 200, r.text
    return r.json()["batch_id"]


def history_actions(client, record_id):
    return [h["action"] for h in client.get(f"/api/records/{record_id}").json()["history"]]


def test_correction_reruns_validation_and_matching(client):
    b = load_harbor(client)
    rec = find(records_by(client, b), file_name="tarnwood_TP-5520.pdf")
    assert rec["match_status"] == "invalid" and "missing_required" in rec["categories"]

    r = client.post(f"/api/records/{rec['id']}/corrections",
                    json={"values": {"tax_amount": "2,700.00"}, "note": "Tax shown on the supplier's portal"})
    assert r.status_code == 200, r.text
    d = r.json()["record"]
    assert d["validation_status"] == "passed"
    assert d["match_status"] == "matched"
    assert d["fields"]["tax_amount"]["status"] == "user_corrected"
    assert d["fields"]["tax_amount"]["original"] is None  # the extracted (missing) value is kept
    assert d["partner"]["match_status"] == "matched"
    assert "corrected" in history_actions(client, rec["id"])

    # Invalid date corrected to the register's date.
    vel = find(records_by(client, b), file_name="velanto_VFS-3307.pdf")
    assert vel["match_status"] == "invalid" and "invalid_date" in vel["categories"]
    d = client.post(f"/api/records/{vel['id']}/corrections", json={"values": {"invoice_date": "28/02/2025"}}).json()["record"]
    assert d["match_status"] == "matched" and d["fields"]["invoice_date"]["normalized"] == "2025-02-28"


def test_correction_withdraws_approvals_it_affects(client):
    b = load_harbor(client)
    recs = records_by(client, b)
    inv = find(recs, file_name="apex_INV-00123.pdf")
    ref_id = inv["partner_id"]
    assert client.post(f"/api/records/{inv['id']}/approve", json={}).status_code == 200
    assert client.post(f"/api/records/{ref_id}/approve", json={}).status_code == 200

    # Correcting the register row changes the pair's outcome, so both approvals are withdrawn.
    r = client.post(f"/api/records/{ref_id}/corrections", json={"values": {"total_amount": "11,900.00"}})
    assert r.status_code == 200
    inv_after = client.get(f"/api/records/{inv['id']}").json()
    ref_after = client.get(f"/api/records/{ref_id}").json()
    assert inv_after["match_status"] == "mismatched"
    assert inv_after["review_status"] == "awaiting_review"
    assert ref_after["review_status"] == "awaiting_review"
    assert "approval_withdrawn" in history_actions(client, inv["id"])
    assert "approval_withdrawn" in history_actions(client, ref_id)

    # Reverting the correction (null value) restores the extracted value and the match.
    r = client.post(f"/api/records/{ref_id}/corrections", json={"values": {"total_amount": None}})
    assert r.json()["record"]["match_status"] == "matched"
    assert "correction_reverted" in history_actions(client, ref_id)


def test_unrelated_approvals_survive_a_correction(client):
    b = load_harbor(client)
    recs = records_by(client, b)
    keep = find(recs, file_name="bluecrest_BOS-2025-0042.pdf")
    client.post(f"/api/records/{keep['id']}/approve", json={})
    target = find(recs, file_name="tarnwood_TP-5520.pdf")
    client.post(f"/api/records/{target['id']}/corrections", json={"values": {"tax_amount": "2700.00"}})
    assert client.get(f"/api/records/{keep['id']}").json()["review_status"] == "approved"


def test_approval_with_open_issues_needs_a_note(client):
    b = load_harbor(client)
    rec = find(records_by(client, b), file_name="orchid_OLC-1450.pdf")
    assert rec["match_status"] == "matched" and "arithmetic" in rec["categories"]
    r = client.post(f"/api/records/{rec['id']}/approve", json={})
    assert r.status_code == 400 and "note" in r.json()["detail"]
    r = client.post(f"/api/records/{rec['id']}/approve", json={"note": "Supplier confirmed total by email"})
    assert r.status_code == 200 and r.json()["review_status"] == "approved"
    # Approving twice is refused; reopen first.
    assert client.post(f"/api/records/{rec['id']}/approve", json={"note": "x"}).status_code == 409
    assert client.post(f"/api/records/{rec['id']}/reopen", json={}).json()["review_status"] == "awaiting_review"


def test_excluding_a_duplicate_lets_the_other_copy_match(client):
    b = load_harbor(client)
    recs = records_by(client, b)
    original = find(recs, file_name="quillmark_QS-0091.pdf")
    copy = find(recs, file_name="quillmark_QS-0091_resent.pdf")
    assert original["match_status"] == copy["match_status"] == "ambiguous"
    assert client.post(f"/api/records/{copy['id']}/exclude", json={"reason": " "}).status_code == 400
    r = client.post(f"/api/records/{copy['id']}/exclude", json={"reason": "Duplicate copy re-sent by supplier"})
    assert r.status_code == 200 and r.json()["review_status"] == "excluded"
    after = client.get(f"/api/records/{original['id']}").json()
    assert after["match_status"] == "matched"
    assert "duplicate" not in after["categories"]
    # Reopening the excluded copy makes both ambiguous again.
    client.post(f"/api/records/{copy['id']}/reopen", json={})
    assert client.get(f"/api/records/{original['id']}").json()["match_status"] == "ambiguous"


def test_manual_link_for_ambiguous_register_rows(client):
    b = load_harbor(client)
    recs = records_by(client, b)
    inv = find(recs, file_name="tarnwood_TP-5531.pdf")
    detail = client.get(f"/api/records/{inv['id']}").json()
    candidates = [c["id"] for c in detail["candidates"]]
    assert len(candidates) == 2
    not_candidate = find(recs, file_name="apex_INV-00123.pdf")["partner_id"]
    assert client.post(f"/api/records/{inv['id']}/link", json={"reference_id": not_candidate}).status_code == 400
    r = client.post(f"/api/records/{inv['id']}/link", json={"reference_id": candidates[0], "note": "Row 16 is a re-entry"})
    assert r.status_code == 200, r.text
    linked = r.json()
    assert linked["match_status"] == "matched" and linked["partner_id"] == candidates[0]
    other = client.get(f"/api/records/{candidates[1]}").json()
    assert other["match_status"] == "no_invoice"
    r = client.delete(f"/api/records/{inv['id']}/link")
    assert r.json()["match_status"] == "ambiguous"


def test_notes_are_kept_in_history(client):
    b = load_harbor(client)
    rec = records_by(client, b)[0]
    assert client.post(f"/api/records/{rec['id']}/notes", json={"note": ""}).status_code == 400
    client.post(f"/api/records/{rec['id']}/notes", json={"note": "Called supplier"})
    hist = client.get(f"/api/records/{rec['id']}").json()["history"]
    assert hist[-1]["action"] == "note" and hist[-1]["note"] == "Called supplier"


def test_source_files_are_stored_unchanged(client):
    b = load_harbor(client)
    rec = find(records_by(client, b), file_name="tarnwood_TP-5520.pdf")
    client.post(f"/api/records/{rec['id']}/corrections", json={"values": {"tax_amount": "2700.00"}})
    served = client.get(f"/api/files/{rec['file_id']}/content")
    assert served.status_code == 200 and served.headers["content-type"] == "application/pdf"
    original = (SAMPLE_DIR / "harbor_lane" / "invoices" / "tarnwood_TP-5520.pdf").read_bytes()
    assert hashlib.sha256(served.content).hexdigest() == hashlib.sha256(original).hexdigest()


def test_unknown_ids_return_404(client):
    assert client.get("/api/records/99999").status_code == 404
    assert client.get("/api/files/99999/content").status_code == 404
    assert client.get("/api/batches/99999").status_code == 404


def test_work_survives_a_restart(data_dir):
    with TestClient(create_app(str(data_dir))) as c1:
        b = load_harbor(c1)
        rec = find(records_by(c1, b), file_name="tarnwood_TP-5520.pdf")
        c1.post(f"/api/records/{rec['id']}/corrections", json={"values": {"tax_amount": "2700.00"}})
        c1.post(f"/api/records/{rec['id']}/approve", json={"note": "checked"})
        copy = find(records_by(c1, b), file_name="quillmark_QS-0091_resent.pdf")
        c1.post(f"/api/records/{copy['id']}/exclude", json={"reason": "duplicate"})
        before = records_by(c1, b)

    # A brand-new application instance on the same data directory.
    with TestClient(create_app(str(data_dir))) as c2:
        after = records_by(c2, b)
        assert [(r["id"], r["match_status"], r["review_status"], r["validation_status"]) for r in after] == \
               [(r["id"], r["match_status"], r["review_status"], r["validation_status"]) for r in before]
        d = c2.get(f"/api/records/{rec['id']}").json()
        assert d["review_status"] == "approved" and d["corrections"] == {"tax_amount": "2700.00"}
        assert {"corrected", "approved"} <= {h["action"] for h in d["history"]}
        assert c2.get("/api/batches").json()[0]["counts"]["review"]["approved"] == 1


def test_delete_batch_removes_its_records_and_files(client, data_dir):
    b = load_harbor(client)
    assert (data_dir / "uploads" / f"batch_{b}").is_dir()
    assert client.delete(f"/api/batches/{b}").status_code == 204
    assert client.get(f"/api/batches/{b}").status_code == 404
    assert not (data_dir / "uploads" / f"batch_{b}").exists()
