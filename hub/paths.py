"""프로젝트·outputs 경로 (부트스트랩/엔진 초기화 없이 import 가능)."""

from __future__ import annotations

from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def project_root() -> Path:
    return _PROJECT_ROOT


def outputs_dir() -> Path:
    return _PROJECT_ROOT / "outputs"


def breaker_output_dir() -> Path:
    return outputs_dir() / "breaker"


def diver_output_dir() -> Path:
    return outputs_dir() / "diver"


def dejavu_output_dir() -> Path:
    return outputs_dir() / "dejavu"


def match_output_dir() -> Path:
    return outputs_dir() / "match"
