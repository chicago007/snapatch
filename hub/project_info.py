"""프로젝트 메타 — README·웹 UI·CLI에서 공통 사용."""

from __future__ import annotations

from pathlib import Path

AUTHOR_NAME = "조르바신부"
AUTHOR_EMAIL = "chicago007@hotmail.com"
GITHUB_USER = "chicago007"
GITHUB_REPO = "snapatch"
GITHUB_URL = f"https://github.com/{GITHUB_USER}/{GITHUB_REPO}"

# 버전 올릴 때: CHANGELOG.md + docs/DEVELOPMENT_NOTES.md 도 함께 갱신
VERSION = "1.02"
VERSION_LABEL = f"v{VERSION}"


def read_version_label() -> str:
    """디스크의 VERSION을 읽는다 (Streamlit 장시간 실행 시 import 캐시 방지)."""
    path = Path(__file__).resolve()
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("VERSION") and "=" in stripped and "VERSION_LABEL" not in stripped:
            _, rhs = stripped.split("=", 1)
            value = rhs.strip().strip('"').strip("'")
            if value:
                return f"v{value}"
    return VERSION_LABEL
