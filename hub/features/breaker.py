"""breaker — 시황 속보 생성 (capstone01 / Gemini)."""

from __future__ import annotations

import os
import time
from datetime import datetime

import streamlit as st

from hub import bootstrap

bootstrap.init()

from engines.breaker.breaker import (  # noqa: E402
    ACCURATE_PRESET,
    DEFAULT_SOURCES,
    FAST_PRESET,
    KST,
    get_gemini_api_key,
    now_kst_label,
    save_report,
    stream_briefing,
)


def _format_elapsed(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.1f}초"
    minutes = int(seconds // 60)
    remainder = seconds % 60
    return f"{minutes}분 {remainder:.1f}초"


def _render_settings() -> None:
    """모델·매체 목록 설정 — 화면 하단에 배치."""
    with st.expander("⚙️ 설정 — 모델 · 매체 목록", expanded=False):
        st.text_input(
            "모델 (GEMINI_MODEL)",
            key="breaker_model",
        )
        st.text_area(
            "매체 목록 (콤마 구분, 비우면 기본 10곳)",
            key="breaker_sources",
            height=90,
        )
        st.checkbox(
            "outputs/breaker 폴더에 저장",
            key="breaker_save",
        )


def render() -> None:
    st.header("📊 breaker — 시황 속보")
    st.caption("Gemini 로 한국어 시황 리포트를 일관된 포맷으로 생성합니다.")

    api_key = get_gemini_api_key()
    if not api_key:
        st.error(
            "GEMINI_API_KEY 가 설정되지 않았습니다. "
            "`.env` 파일 또는 환경변수를 확인하세요.",
            icon="🚫",
        )
        return

    st.session_state.setdefault(
        "breaker_model",
        os.environ.get("GEMINI_MODEL", "gemini-2.5-pro"),
    )
    st.session_state.setdefault(
        "breaker_sources",
        os.environ.get("BRIEFING_SOURCES", ", ".join(DEFAULT_SOURCES)),
    )
    st.session_state.setdefault("breaker_save", True)
    st.session_state.setdefault("breaker_fast", "fast")

    mode_col, btn_col = st.columns([2, 1])
    with mode_col:
        st.radio(
            "생성 모드",
            options=["fast", "accurate"],
            format_func=lambda value: (
                "빠름 (flash, 검색 생략, ~5~10초)"
                if value == "fast"
                else "정확 (pro, Google 검색, ~20~40초)"
            ),
            horizontal=True,
            key="breaker_fast",
        )
    with btn_col:
        st.write("")
        st.write("")
        generate = st.button(
            "속보 생성",
            type="primary",
            use_container_width=True,
        )
    result_area = st.container()

    _render_settings()

    if not generate:
        return

    use_fast = st.session_state["breaker_fast"] == "fast"
    preset = FAST_PRESET if use_fast else ACCURATE_PRESET
    model = st.session_state["breaker_model"].strip() or preset.model
    raw_sources = st.session_state["breaker_sources"]
    should_save = st.session_state["breaker_save"]

    sources = [
        s.strip()
        for s in raw_sources.split(",")
        if s.strip()
    ] or list(DEFAULT_SOURCES)

    when = datetime.now(tz=KST)
    label = now_kst_label(when)

    with result_area:
        started_at = time.perf_counter()
        spinner_msg = (
            "리포트 생성 중입니다... (빠른 모드, 스트리밍)"
            if use_fast
            else "리포트 생성 중입니다... (정확 모드, 스트리밍)"
        )
        with st.spinner(spinner_msg):
            try:
                report = st.write_stream(
                    stream_briefing(
                        api_key,
                        model,
                        sources,
                        label,
                        timeout=preset.timeout,
                        use_google_search=preset.use_google_search,
                        max_output_tokens=preset.max_output_tokens,
                        temperature=preset.temperature,
                    ),
                )
            except Exception as exc:  # noqa: BLE001
                st.error(f"생성 실패: {exc}", icon="🚫")
                return
        elapsed = time.perf_counter() - started_at

        st.success(f"생성이 완료되었습니다. (소요: {_format_elapsed(elapsed)})")

        file_name = when.astimezone(KST).strftime("%Y-%m-%d_%H-%M_KST.md")
        st.download_button(
            "마크다운 다운로드",
            data=report,
            file_name=file_name,
            mime="text/markdown",
            use_container_width=True,
        )

        if should_save:
            saved = save_report(report, when)
            st.caption(f"저장 완료: `{saved}`")
