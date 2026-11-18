"""HTTP API. Thin: validation of request shapes, then a call into ``services``."""

from __future__ import annotations

import sqlite3
from typing import Iterator

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from . import __version__, db, samples, services
from .export import build_workbook
from .labels import all_labels
from .settings import Settings

router = APIRouter()

MEDIA_TYPES = {
    "pdf": "application/pdf",
    "csv": "text/csv; charset=utf-8",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_conn(request: Request) -> Iterator[sqlite3.Connection]:
    conn = db.connect(request.app.state.settings.db_path)
    try:
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


class BatchCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    template_id: str = "supplier_invoice"


class MappingBody(BaseModel):
    sheet: str | None = None
    header_row: int | None = Field(default=None, ge=1, le=1000)
    mapping: dict[str, str | None]
    date_order: str
    default_currency: str | None = None
    profile_name: str | None = Field(default=None, max_length=80)


class CorrectionBody(BaseModel):
    values: dict[str, str | None]
    note: str | None = Field(default=None, max_length=2000)


class NoteBody(BaseModel):
    note: str | None = Field(default=None, max_length=2000)


class ReasonBody(BaseModel):
    reason: str = Field(max_length=2000)


class LinkBody(BaseModel):
    reference_id: int
    note: str | None = Field(default=None, max_length=2000)


# ---------------------------------------------------------------- meta

@router.get("/health")
def health():
    return {"status": "ok", "version": __version__}


@router.get("/meta")
def meta(settings: Settings = Depends(get_settings)):
    return {
        "version": __version__,
        "labels": all_labels(),
        "templates": services.list_template_summaries(),
        "limits": {"max_upload_mb": settings.max_upload_bytes // (1024 * 1024),
                   "max_files_per_upload": settings.max_files_per_upload},
    }


@router.get("/templates")
def templates():
    return services.list_template_summaries()


@router.get("/templates/{template_id}")
def template(template_id: str):
    return services.template_summary(template_id)


@router.get("/mapping-profiles")
def mapping_profiles(conn=Depends(get_conn)):
    return services.list_profiles(conn)


# ---------------------------------------------------------------- samples

@router.get("/samples")
def list_samples(settings: Settings = Depends(get_settings)):
    return samples.list_samples(settings)


@router.post("/samples/{sample_id}/load")
def load_sample(sample_id: str, conn=Depends(get_conn), settings: Settings = Depends(get_settings)):
    return samples.load_sample(conn, settings, sample_id)


# ---------------------------------------------------------------- batches

@router.get("/batches")
def list_batches(conn=Depends(get_conn)):
    return services.list_batches(conn)


@router.post("/batches", status_code=201)
def create_batch(body: BatchCreate, conn=Depends(get_conn)):
    batch_id = services.create_batch(conn, body.name, body.template_id)
    return services.get_batch(conn, batch_id)


@router.get("/batches/{batch_id}")
def get_batch(batch_id: int, conn=Depends(get_conn)):
    return services.get_batch(conn, batch_id)


@router.delete("/batches/{batch_id}", status_code=204)
def delete_batch(batch_id: int, conn=Depends(get_conn), settings: Settings = Depends(get_settings)):
    services.delete_batch(conn, settings, batch_id)
    return Response(status_code=204)


@router.post("/batches/{batch_id}/files", status_code=201)
def upload_files(batch_id: int, role: str = Form(...), files: list[UploadFile] = File(...),
                 conn=Depends(get_conn), settings: Settings = Depends(get_settings)):
    if len(files) > settings.max_files_per_upload:
        raise services.ServiceError(f"Upload at most {settings.max_files_per_upload} files at a time.")
    out = []
    for upload in files:
        data = upload.file.read(settings.max_upload_bytes + 1)
        out.append(services.add_file(conn, settings, batch_id, role, upload.filename or "unnamed", data))
    return out


@router.post("/batches/{batch_id}/process")
def process_batch(batch_id: int, conn=Depends(get_conn), settings: Settings = Depends(get_settings)):
    return services.process_batch(conn, settings, batch_id)


@router.get("/batches/{batch_id}/records")
def list_records(batch_id: int, role: str | None = None, match_status: str | None = None,
                 validation_status: str | None = None, review_status: str | None = None,
                 category: str | None = None, q: str | None = Query(default=None, max_length=200),
                 corrected: bool | None = None, conn=Depends(get_conn)):
    return services.list_records(conn, batch_id, role=role, match_status=match_status,
                                 validation_status=validation_status, review_status=review_status,
                                 category=category, q=q, corrected=corrected)


@router.get("/batches/{batch_id}/history")
def batch_history(batch_id: int, conn=Depends(get_conn)):
    return services.batch_history(conn, batch_id)


@router.get("/batches/{batch_id}/export")
def export_batch(batch_id: int, conn=Depends(get_conn)):
    data, filename = build_workbook(conn, batch_id)
    return Response(content=data, media_type=MEDIA_TYPES["xlsx"],
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


# ---------------------------------------------------------------- files

@router.get("/files/{file_id}/preview")
def file_preview(file_id: int, sheet: str | None = None, header_row: int | None = Query(default=None, ge=1, le=1000),
                 date_column: str | None = Query(default=None, max_length=300),
                 conn=Depends(get_conn), settings: Settings = Depends(get_settings)):
    return services.file_preview(conn, settings, file_id, sheet=sheet, header_row=header_row, date_column=date_column)


@router.post("/files/{file_id}/mapping")
def confirm_mapping(file_id: int, body: MappingBody, conn=Depends(get_conn), settings: Settings = Depends(get_settings)):
    return services.confirm_mapping(conn, settings, file_id, sheet=body.sheet, header_row=body.header_row,
                                    mapping=body.mapping, date_order=body.date_order,
                                    default_currency=body.default_currency, profile_name=body.profile_name)


@router.delete("/files/{file_id}", status_code=204)
def remove_file(file_id: int, conn=Depends(get_conn)):
    services.remove_file(conn, file_id)
    return Response(status_code=204)


@router.get("/files/{file_id}/content")
def file_content(file_id: int, conn=Depends(get_conn), settings: Settings = Depends(get_settings)):
    path, f = services.stored_path(conn, settings, file_id)
    kind = f["kind"] or "bin"
    return FileResponse(path, media_type=MEDIA_TYPES.get(kind, "application/octet-stream"),
                        filename=f["original_name"],
                        content_disposition_type="inline" if kind == "pdf" else "attachment")


@router.get("/files/{file_id}/pages")
def file_pages(file_id: int, conn=Depends(get_conn)):
    return services.file_pages(conn, file_id)


# ---------------------------------------------------------------- records

@router.get("/records/{record_id}")
def record_detail(record_id: int, conn=Depends(get_conn)):
    return services.record_detail(conn, record_id)


@router.post("/records/{record_id}/corrections")
def correct(record_id: int, body: CorrectionBody, conn=Depends(get_conn)):
    return services.correct_record(conn, record_id, body.values, body.note)


@router.post("/records/{record_id}/approve")
def approve(record_id: int, body: NoteBody, conn=Depends(get_conn)):
    return services.approve_record(conn, record_id, body.note)


@router.post("/records/{record_id}/exclude")
def exclude(record_id: int, body: ReasonBody, conn=Depends(get_conn)):
    return services.exclude_record(conn, record_id, body.reason)


@router.post("/records/{record_id}/reopen")
def reopen(record_id: int, body: NoteBody, conn=Depends(get_conn)):
    return services.reopen_record(conn, record_id, body.note)


@router.post("/records/{record_id}/notes")
def note(record_id: int, body: NoteBody, conn=Depends(get_conn)):
    return services.add_note(conn, record_id, body.note or "")


@router.post("/records/{record_id}/link")
def link(record_id: int, body: LinkBody, conn=Depends(get_conn)):
    return services.link_record(conn, record_id, body.reference_id, body.note)


@router.delete("/records/{record_id}/link")
def unlink(record_id: int, conn=Depends(get_conn)):
    return services.unlink_record(conn, record_id)
