"""breaker — 시황 속보 생성 (capstone01 / Gemini)."""

from __future__ import annotations

import os
import time
from datetime import datetime

import streamlit as st

from snapatch import bootstrap

bootstrap.init()

from briefing import (  # noqa: E402  (vendor 경로 등록 후 import)
    ACCURATE_PRESET,
    FAST_PRESET,
    KST,
    detect_missing_commodities,
    generate_briefing,
    generate_with_retry,
    get_gemini_api_key,
    now_kst_label,
    parse_sources,
    save_report,
)

SOURCE_DEFAULT = (
    "네이버 금융뉴스, 구글 금융뉴스, 한국경제, 연합뉴스, "
    "KRX, investing.com, Yahoo Finance, Bloomberg, Reuters, CNBC"
)


def _render_controls() -> tuple[str, str | None, str, bool]:
    col_mode, col_save = st.columns([2, 1])
    with col_mode:
        run_mode = st.radio(
            "실행 방식",
            options=["preset", "once"],
            index=0,
            horizontal=True,
            format_func=lambda k: {
                "preset": "프리셋 (빠른·정확 + 원자재 재시도)",
                "once": "단일 호출 (CLI once 동일)",
            }[k],
        )
    mode_label: str | None = None
    if run_mode == "preset":
        mode_label = st.radio(
            "생성 모드",
            options=["빠른 모드", "정확 모드"],
            index=0,
            horizontal=True,
        )
    with col_save:
        should_save = st.checkbox("reports 폴더에 저장", value=True)

    raw_sources = st.text_area(
        "매체 목록 (콤마 구분)",
        value=os.environ.get("BRIEFING_SOURCES", SOURCE_DEFAULT),
        height=90,
    )
    return run_mode, mode_label, raw_sources, should_save


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

    run_mode, mode_label, raw_sources, should_save = _render_controls()
    preset = (FAST_PRESET if mode_label == "빠른 모드" else ACCURATE_PRESET) \
        if mode_label else None
    sources = parse_sources(raw_sources)

    if run_mode == "once":
        model_for_run = st.text_input(
            "모델 (GEMINI_MODEL)",
            value=os.environ.get("GEMINI_MODEL", "gemini-2.5-pro"),
        ).strip()
    else:
        assert preset is not None
        override = st.text_input(
            "모델 오버라이드 (비우면 모드 기본값 사용)",
            value="",
            placeholder=preset.model,
        ).strip()
        model_for_run = override or preset.model

    if not st.button("속보 생성", type="primary", use_container_width=True):
        return

    start = time.perf_counter()
    label = now_kst_label()
    with st.spinner("리포트 생성 중입니다..."):
        try:
            if run_mode == "once":
                report = generate_briefing(api_key, model_for_run, sources, label)
                attempts = 1
                missing = detect_missing_commodities(report)
            else:
                assert preset is not None
                report, attempts, missing = generate_with_retry(
                    api_key=api_key,
                    preset=preset,
                    sources=sources,
                    now_kst=label,
                    model_override=(
                        model_for_run if model_for_run != preset.model else None
                    ),
                )
        except Exception as exc:  # noqa: BLE001
            st.error(f"생성 실패: {exc}", icon="🚫")
            return

    elapsed = time.perf_counter() - start
    st.success("생성이 완료되었습니다.")

    c1, c2, c3 = st.columns(3)
    c1.metric("소요 시간(초)", f"{elapsed:.1f}")
    c2.metric("시도 횟수", str(attempts))
    c3.metric("실행", "once" if run_mode == "once" else (mode_label or ""))

    if missing:
        st.warning("원자재 항목 누락 가능: " + ", ".join(missing), icon="⚠️")
    else:
        st.info("원자재(WTI/금/은) 항목 확인 완료", icon="✅")

    st.markdown(report)

    file_name = (
        f"briefing_{datetime.now(tz=KST).strftime('%Y-%m-%d_%H-%M_KST')}.md"
    )
    st.download_button(
        "마크다운 다운로드",
        data=report,
        file_name=file_name,
        mime="text/markdown",
        use_container_width=True,
    )

    if should_save:
        saved = save_report(report, datetime.now(tz=KST))
        st.caption(f"저장 완료: `{saved}`")
