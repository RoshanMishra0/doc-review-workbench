"""Paths and limits. Everything local; nothing here talks to a network service."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
BACKEND_DIR = APP_DIR.parent
REPO_DIR = BACKEND_DIR.parent
TEMPLATE_DIR = APP_DIR / "template_configs"
SAMPLE_DIR = REPO_DIR / "sample_data"
FRONTEND_DIST = REPO_DIR / "frontend" / "dist"


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    max_upload_bytes: int = 20 * 1024 * 1024
    max_files_per_upload: int = 100
    sample_dir: Path = SAMPLE_DIR
    frontend_dist: Path = FRONTEND_DIST

    @property
    def db_path(self) -> Path:
        return self.data_dir / "workbench.db"

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"


def load_settings(data_dir: str | os.PathLike[str] | None = None) -> Settings:
    chosen = data_dir or os.environ.get("DRW_DATA_DIR") or (BACKEND_DIR / "data")
    path = Path(chosen).resolve()
    path.mkdir(parents=True, exist_ok=True)
    (path / "uploads").mkdir(parents=True, exist_ok=True)
    return Settings(data_dir=path)
