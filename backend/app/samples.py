"""Load the synthetic sample dataset through the normal ingestion pipeline.

The loader reads the committed sample files from disk and passes their bytes
to the same ``add_file`` / ``confirm_mapping`` / ``process_batch`` functions
used for uploads. Spreadsheet mappings are confirmed automatically only when
a saved mapping matches the headings exactly, or every required field has a
configured alias match. Otherwise the file waits for the user to map it,
exactly like an upload.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import services
from .ingestion import mapping_problems
from .settings import Settings

ACTOR = "sample loader"


def _manifest(settings: Settings) -> dict:
    path = settings.sample_dir / "manifest.json"
    if not path.is_file():
        raise services.NotFound("The sample dataset is not present. Run sample_data/generate_samples.py first.")
    return json.loads(path.read_text(encoding="utf-8"))


def list_samples(settings: Settings) -> list[dict]:
    manifest = _manifest(settings)
    out = []
    for s in manifest.get("samples", []):
        out.append({k: s[k] for k in ("id", "name", "description", "template_id")} | {"file_count": len(s["files"])})
    return out


def _sample_file(settings: Settings, rel: str) -> Path:
    root = settings.sample_dir.resolve()
    path = (root / rel).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise services.ServiceError(f"Sample file '{rel}' is missing.")
    return path


def load_sample(conn, settings: Settings, sample_id: str) -> dict:
    manifest = _manifest(settings)
    sample = next((s for s in manifest.get("samples", []) if s["id"] == sample_id), None)
    if sample is None:
        raise services.NotFound(f"Sample '{sample_id}' was not found.")
    batch_id = services.create_batch(conn, f"{sample['name']} - synthetic demo", sample["template_id"],
                                     sample_id=sample_id, actor=ACTOR)
    file_ids = []
    for entry in sample["files"]:
        path = _sample_file(settings, entry["path"])
        added = services.add_file(conn, settings, batch_id, entry["role"], path.name, path.read_bytes(), actor=ACTOR)
        file_ids.append(added["id"])
    auto_mapped, waiting = [], []
    template = services.get_template(sample["template_id"])
    for fid in file_ids:
        f = conn.execute("SELECT * FROM files WHERE id=?", (fid,)).fetchone()
        if f["status"] != "needs_mapping":
            continue
        preview = services.file_preview(conn, settings, fid)
        mapping = preview["proposed_mapping"]
        problems = mapping_problems(mapping, preview["headers"], template, preview["default_currency"])
        if problems:
            waiting.append(f["original_name"])
            continue
        source = preview["proposed_from"]
        services.confirm_mapping(conn, settings, fid, sheet=preview["sheet"], header_row=preview["header_row"],
                                 mapping=mapping, date_order=preview["date_order"],
                                 default_currency=preview["default_currency"], actor=ACTOR,
                                 note=f"Confirmed automatically by the sample loader from {source}.")
        auto_mapped.append(f["original_name"])
    summary = services.process_batch(conn, settings, batch_id, actor=ACTOR)
    return {"batch_id": batch_id, "auto_mapped": auto_mapped, "waiting_for_mapping": waiting, "summary": summary}
