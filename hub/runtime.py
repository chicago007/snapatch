"""웹 배포 환경 감지 — Streamlit Cloud vs 로컬."""

from __future__ import annotations

import os
from pathlib import Path


def is_streamlit_cloud() -> bool:
    """Streamlit Community Cloud 등 /mount/src 에서 실행 중인지."""
    if os.getenv("SNAPATCH_STREAMLIT_CLOUD", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }:
        return True
    return str(Path.cwd()).startswith("/mount/src")


def can_persist_outputs() -> bool:
    """outputs/ 폴더에 파일을 영구 보관할 수 있는 로컬 환경인지."""
    return not is_streamlit_cloud()
