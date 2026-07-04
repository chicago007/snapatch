"""프로젝트 루트 경로와 환경변수(.env)를 한 번만 초기화한다.

엔진 코드는 `engines.<feature>` 패키지로 임포트한다
(예: `from engines.diver.pipeline import run_pipeline`).
Streamlit Cloud처럼 진입점이 하위 파일일 때도 `engines`/`hub` 패키지를
찾을 수 있도록 프로젝트 루트를 sys.path 에 등록한다.
"""

from __future__ import annotations

import sys
from pathlib import Path

from hub.paths import (
    breaker_output_dir,
    dejavu_output_dir,
    diver_output_dir,
    match_output_dir,
    outputs_dir,
    project_root,
)

_PROJECT_ROOT = project_root()
_ENGINES_ROOT = _PROJECT_ROOT / "engines"

_initialized = False


def engines_root() -> Path:
    return _ENGINES_ROOT


def init() -> None:
    """프로젝트 루트 sys.path 등록 + .env 로드 (idempotent)."""
    global _initialized
    if _initialized:
        return

    root_str = str(_PROJECT_ROOT)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)

    try:
        from dotenv import load_dotenv

        load_dotenv(_PROJECT_ROOT / ".env")
    except ImportError:
        pass

    _initialized = True
