"""breaker — 시황 속보 생성 (capstone01 / Gemini)."""

from __future__ import annotations

import os
from datetime import datetime

import streamlit as st

from snapatch import bootstrap

bootstrap.init()

from breaker import (  # noqa: E402
    DEFAULT_SOURCES,
    KST,
    generate_briefing,
    get_gemini_api_key,
    now_kst_label,
    save_report,
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

    model = st.text_input(
        "모델 (GEMINI_MODEL)",
        value=os.environ.get("GEMINI_MODEL", "gemini-2.5-pro"),
    ).strip()
    raw_sources = st.text_area(
        "매체 목록 (콤마 구분, 비우면 기본 10곳)",
        value=os.environ.get(
            "BRIEFING_SOURCES",
            ", ".join(DEFAULT_SOURCES),
        ),
        height=90,
    )
    should_save = st.checkbox("reports 폴더에 저장", value=True)

    if not st.button("속보 생성", type="primary", use_container_width=True):
        return

    sources = [
        s.strip()
        for s in raw_sources.split(",")
        if s.strip()
    ] or list(DEFAULT_SOURCES)

    when = datetime.now(tz=KST)
    label = now_kst_label(when)

    with st.spinner("리포트 생성 중입니다... (보통 20~40초 소요)"):
        try:
            report = generate_briefing(api_key, model, sources, label)
        except Exception as exc:  # noqa: BLE001
            st.error(f"생성 실패: {exc}", icon="🚫")
            return

    st.success("생성이 완료되었습니다.")
    st.markdown(report)

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
