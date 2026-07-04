"""diver — 키워드 뉴스 수집/분석 (capstone02 / Naver + Gemini)."""

from __future__ import annotations

import os
import time

import streamlit as st

from hub import bootstrap

bootstrap.init()

from config import Settings  # noqa: E402
from diver import (  # noqa: E402
    SavedReports,
    format_md,
    save_result_files,
)
from pipeline import run_pipeline  # noqa: E402


def _check_credentials() -> list[str]:
    settings = Settings()
    missing: list[str] = []
    if not settings.naver_client_id or not settings.naver_client_secret:
        missing.append("NAVER_CLIENT_ID / NAVER_CLIENT_SECRET")
    if settings.uses_vertexai():
        if not settings.google_cloud_project:
            missing.append("GOOGLE_CLOUD_PROJECT (Vertex AI)")
    elif not (os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")):
        missing.append("GOOGLE_API_KEY / GEMINI_API_KEY")
    return missing


def _format_elapsed(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.1f}초"
    minutes = int(seconds // 60)
    remainder = seconds % 60
    return f"{minutes}분 {remainder:.1f}초"


def render() -> None:
    st.header("🔎 diver — 키워드 뉴스 분석")
    st.caption("네이버 뉴스 검색 + Gemini 구조화 분석으로 키워드를 심층 분석합니다.")

    missing = _check_credentials()
    if missing:
        st.error(
            "환경변수가 설정되지 않았습니다: " + ", ".join(missing),
            icon="🚫",
        )
        st.caption(
            "`.env` 또는 Streamlit Secrets에 키를 넣으세요. "
            "(Vertex: gcloud 인증 / API 키: GOOGLE_GENAI_USE_VERTEXAI=false)"
        )
        return

    settings = Settings()

    col_q, col_btn = st.columns([3, 1])
    with col_q:
        query = st.text_input(
            "검색 키워드",
            value="",
            placeholder="예: 삼성전자, 2차전지, 금리인하",
        )
    with col_btn:
        st.write("")
        st.write("")
        run = st.button("분석", type="primary", use_container_width=True)

    c1, c2, c3 = st.columns(3)
    target_count = c1.number_input(
        "목표 기사 수",
        min_value=1,
        max_value=30,
        value=settings.default_target_count,
    )
    max_days = c2.number_input(
        "최대 검색 기간(일)",
        min_value=1,
        max_value=90,
        value=settings.default_max_days,
    )
    fast = c3.toggle("빠른 모드 (원문 생략)", value=settings.skip_content)
    save_report = st.checkbox("outputs/diver 폴더에 저장", value=True)

    if not run:
        return
    if not query.strip():
        st.warning("키워드를 입력하세요.", icon="⚠️")
        return

    started_at = time.perf_counter()
    with st.spinner(f"'{query}' 뉴스 수집/분석 중..."):
        try:
            result = run_pipeline(
                query=query.strip(),
                target_count=int(target_count),
                max_days=int(max_days),
                debug=False,
                skip_content=bool(fast),
            )
        except Exception as exc:  # noqa: BLE001
            st.error(f"분석 실패: {exc}", icon="🚫")
            return

    elapsed = time.perf_counter() - started_at
    st.success(f"분석이 완료되었습니다. (소요: {_format_elapsed(elapsed)})")

    saved: SavedReports | None = None
    if save_report:
        try:
            saved = save_result_files(result, query.strip())
            st.caption(f"저장 완료: `{saved.md_path}`")
        except OSError as exc:
            st.warning(f"결과 파일 저장 실패: {exc}", icon="⚠️")

    report_md = format_md(result)
    st.markdown(report_md)

    st.download_button(
        "Markdown 다운로드",
        data=report_md.encode("utf-8"),
        file_name=(
            saved.md_path.name if saved is not None else "diver_분석.md"
        ),
        mime="text/markdown",
        use_container_width=True,
        key="dl_diver_md",
    )
