"""Data retention and deletion when a file is removed or a batch is deleted."""

import io
import sqlite3

from openpyxl import load_workbook

from .conftest import find, records_by


def load_harbor(client):
    r = client.post("/api/samples/harbor_lane/load")
    assert r.status_code == 200, r.text
    return r.json()["batch_id"]


def db(data_dir):
    conn = sqlite3.connect(data_dir / "workbench.db")
    conn.row_factory = sqlite3.Row
    return conn


def test_removing_a_file_deletes_its_content_and_keeps_an_account(client, data_dir):
    b = load_harbor(client)
    rec = find(records_by(client, b), file_name="tarnwood_TP-5520.pdf")
    fid = rec["file_id"]
    client.post(f"/api/records/{rec['id']}/corrections", json={"values": {"tax_amount": "2,700.00"}, "note": "from portal"})
    with db(data_dir) as conn:
        stored_name = conn.execute("SELECT stored_name FROM files WHERE id=?", (fid,)).fetchone()[0]
    stored = data_dir / "uploads" / stored_name

    # Retained while the file is part of the batch.
    assert stored.is_file()
    assert client.get(f"/api/files/{fid}/content").status_code == 200
    assert client.get(f"/api/files/{fid}/pages").json()[0]["text"].startswith("Tarnwood")

    assert client.delete(f"/api/files/{fid}").status_code == 204

    # Content, extracted text and records are gone and cannot be fetched.
    assert not stored.exists()
    gone = client.get(f"/api/files/{fid}/content")
    assert gone.status_code == 410 and "removed" in gone.json()["detail"]
    assert client.get(f"/api/files/{fid}/pages").status_code == 410
    assert client.get(f"/api/records/{rec['id']}").status_code == 404
    with db(data_dir) as conn:
        assert conn.execute("SELECT COUNT(*) FROM file_pages WHERE file_id=?", (fid,)).fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM records WHERE file_id=?", (fid,)).fetchone()[0] == 0
        row = conn.execute("SELECT * FROM files WHERE id=?", (fid,)).fetchone()
        assert row["stored_name"] is None
        # Values copied from the removed file into the history are redacted; the actions stay.
        hist = conn.execute("SELECT * FROM history WHERE record_id=? AND action='corrected'", (rec["id"],)).fetchall()
        assert hist and all(h["old_value"] is None and h["new_value"] is None for h in hist)
        assert hist[0]["field"] == "tax_amount" and hist[0]["note"] == "from portal"

    # The upload stays accounted for: name, size, hash, status and when it was removed.
    f = next(x for x in client.get(f"/api/batches/{b}").json()["files"] if x["id"] == fid)
    assert f["status"] == "removed" and f["original_name"] == "tarnwood_TP-5520.pdf"
    assert f["sha256"] and f["size_bytes"] > 0 and f["removed_at"]
    wb = load_workbook(io.BytesIO(client.get(f"/api/batches/{b}/export").content))
    rejected = {r[1]: r for r in wb["Rejected files"].iter_rows(min_row=2, values_only=True)}
    assert "tarnwood_TP-5520.pdf" in rejected

    # The register row it was paired with is now honestly unmatched, and removal is idempotent.
    assert client.delete(f"/api/files/{fid}").status_code == 204


def test_rejected_file_bytes_are_retained_until_removed(client, data_dir):
    b = load_harbor(client)
    scan = next(x for x in client.get(f"/api/batches/{b}").json()["files"] if x["original_name"] == "scan_marlow_MSU-88120.pdf")
    assert scan["status"] == "rejected"
    assert client.get(f"/api/files/{scan['id']}/content").status_code == 200
    assert client.delete(f"/api/files/{scan['id']}").status_code == 204
    assert client.get(f"/api/files/{scan['id']}/content").status_code == 410


def test_other_files_are_untouched_by_a_removal(client, data_dir):
    b = load_harbor(client)
    files = client.get(f"/api/batches/{b}").json()["files"]
    target = next(x for x in files if x["original_name"] == "apex_INV-00123.pdf")
    before = {p.name for p in (data_dir / "uploads" / f"batch_{b}").iterdir()}
    client.delete(f"/api/files/{target['id']}")
    after = {p.name for p in (data_dir / "uploads" / f"batch_{b}").iterdir()}
    assert len(before - after) == 1 and len(after) == len(before) - 1
    other = next(x for x in files if x["original_name"] == "bluecrest_BOS-2025-0042.pdf")
    assert client.get(f"/api/files/{other['id']}/content").status_code == 200


def test_deleting_a_batch_removes_all_of_its_data(client, data_dir):
    b = load_harbor(client)
    keep = load_harbor(client)
    assert client.delete(f"/api/batches/{b}").status_code == 204
    assert not (data_dir / "uploads" / f"batch_{b}").exists()
    with db(data_dir) as conn:
        for table in ("files", "records", "issues", "history"):
            assert conn.execute(f"SELECT COUNT(*) FROM {table} WHERE batch_id=?", (b,)).fetchone()[0] == 0, table
        assert conn.execute("SELECT COUNT(*) FROM file_pages fp LEFT JOIN files f ON f.id=fp.file_id "
                            "WHERE f.id IS NULL").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM records WHERE batch_id=?", (keep,)).fetchone()[0] == 30


def test_database_from_the_first_version_is_upgraded(tmp_path):
    """A schema-1 database (no files.removed_at) is migrated in place on startup without losing data."""
    from app.db import SCHEMA, init_db

    path = tmp_path / "old.db"
    old_schema = SCHEMA.replace("    processed_at TEXT,\n    removed_at TEXT\n", "    processed_at TEXT\n")
    assert "removed_at" not in old_schema
    conn = sqlite3.connect(path)
    conn.executescript(old_schema)
    conn.execute("INSERT INTO batches (name, template_id, template_version, created_at, updated_at) "
                 "VALUES ('old', 'supplier_invoice', 1, 'x', 'x')")
    conn.execute("PRAGMA user_version=1")
    conn.commit()
    conn.close()

    init_db(path)
    init_db(path)  # idempotent
    conn = sqlite3.connect(path)
    assert "removed_at" in {r[1] for r in conn.execute("PRAGMA table_info(files)")}
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 2
    assert conn.execute("SELECT name FROM batches").fetchone()[0] == "old"
    conn.close()


def test_removing_the_rejected_files_makes_the_batch_complete(client):
    b = load_harbor(client)
    detail = client.get(f"/api/batches/{b}").json()
    comp = detail["counts"]["completeness"]
    assert comp["complete"] is False and len(comp["gaps"]) == 3
    row = find(records_by(client, b), invoice_number="MSU-88120")
    assert "Not every invoice file is fully imported" in " ".join(client.get(f"/api/records/{row['id']}").json()["match"]["explanation"])
    for f in detail["files"]:
        if f["status"] == "rejected":
            assert client.delete(f"/api/files/{f['id']}").status_code == 204
    after = client.get(f"/api/batches/{b}").json()["counts"]["completeness"]
    assert after == {"complete": True, "gaps": []}
    # Without the gap, the explanation no longer hedges.
    assert "Not every" not in " ".join(client.get(f"/api/records/{row['id']}").json()["match"]["explanation"])
