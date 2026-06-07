from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ENGINE_DIR = Path(__file__).resolve().parent
SNAPATCH_ROOT = ENGINE_DIR.parent.parent


def _load_dotenv_from_project() -> None:
    load_dotenv(SNAPATCH_ROOT / ".env", override=True)
    load_dotenv(ENGINE_DIR / ".env", override=False)


_load_dotenv_from_project()


def _get_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _get_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _get_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def _get_output_format() -> str:
    value = os.getenv("DEFAULT_OUTPUT_FORMAT", "json").strip().lower()
    return value if value in {"json", "text"} else "json"


@dataclass(frozen=True)
class Settings:
    naver_client_id: str = os.getenv("NAVER_CLIENT_ID", "")
    naver_client_secret: str = os.getenv("NAVER_CLIENT_SECRET", "")
    google_cloud_project: str = os.getenv("GOOGLE_CLOUD_PROJECT", "")
    google_cloud_location: str = os.getenv("GOOGLE_CLOUD_LOCATION", "global")
    google_genai_use_vertexai: str = os.getenv("GOOGLE_GENAI_USE_VERTEXAI", "true")
    vertex_model: str = os.getenv("VERTEX_MODEL", "gemini-2.5-flash")
    default_target_count: int = _get_int("DEFAULT_TARGET_COUNT", 5)
    default_max_days: int = _get_int("DEFAULT_MAX_DAYS", 30)
    default_output_format: str = _get_output_format()
    skip_content: bool = _get_bool("SKIP_CONTENT", False)
    article_timeout_seconds: float = _get_float("ARTICLE_TIMEOUT_SECONDS", 3.0)
    article_max_workers: int = _get_int("ARTICLE_MAX_WORKERS", 5)
    content_preview_length: int = _get_int("CONTENT_PREVIEW_LENGTH", 1000)
    filter_similar_news: bool = _get_bool("FILTER_SIMILAR_NEWS", True)
    news_similarity_threshold: float = _get_float("NEWS_SIMILARITY_THRESHOLD", 0.82)
    news_token_overlap_threshold: float = _get_float(
        "NEWS_TOKEN_OVERLAP_THRESHOLD",
        0.55,
    )
    post_filter_similar_news: bool = _get_bool(
        "POST_FILTER_SIMILAR_NEWS",
        True,
    )
    post_news_keyword_overlap_threshold: float = _get_float(
        "POST_NEWS_KEYWORD_OVERLAP_THRESHOLD",
        0.55,
    )
    post_news_keyword_min_common: int = _get_int(
        "POST_NEWS_KEYWORD_MIN_COMMON",
        3,
    )

    def validate_naver(self) -> None:
        if not self.naver_client_id or not self.naver_client_secret:
            raise ValueError("NAVER_CLIENT_ID / NAVER_CLIENT_SECRET 환경변수가 필요합니다.")

    def validate_vertex(self) -> None:
        if not self.google_cloud_project:
            raise ValueError("GOOGLE_CLOUD_PROJECT 환경변수가 필요합니다.")


def diver_output_dir() -> Path:
    out = SNAPATCH_ROOT / "outputs" / "diver"
    out.mkdir(parents=True, exist_ok=True)
    return out
