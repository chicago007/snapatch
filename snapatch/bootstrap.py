"""vendor 소스 경로와 환경변수(.env)를 한 번만 초기화한다.

각 캡스톤 원본 코드는 `vendor/<feature>/` 에 그대로 보존되어 있고,
최상위 모듈 이름(`briefing`, `news_harness`, `dejavu00`, `match_engine`)으로
import 할 수 있도록 sys.path 에 등록한다.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_VENDOR_ROOT = _PROJECT_ROOT / "vendor"

_VENDOR_DIRS = ("breaker", "diver", "dejavu", "match")

_initialized = False


def project_root() -> Path:
    return _PROJECT_ROOT


def vendor_root() -> Path:
    return _VENDOR_ROOT


def init() -> None:
    """vendor 경로 등록 + .env 로드 (idempotent)."""
    global _initialized
    if _initialized:
        return

    for name in _VENDOR_DIRS:
        path = _VENDOR_ROOT / name
        if path.is_dir():
            str_path = str(path)
            if str_path not in sys.path:
                sys.path.insert(0, str_path)

    try:
        from dotenv import load_dotenv

        load_dotenv(_PROJECT_ROOT / ".env")
    except ImportError:
        pass

    _initialized = True
