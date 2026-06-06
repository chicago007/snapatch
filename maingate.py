"""snapatch — 주식 분석 통합 웹앱 (Streamlit 진입점).

실행: python -m streamlit run maingate.py
"""

from __future__ import annotations

import streamlit as st

from snapatch import bootstrap

bootstrap.init()

st.set_page_config(
    page_title="snapatch",
    page_icon="📈",
    layout="wide",
)

_FEATURES = {
    "breaker": {
        "icon": "📊",
        "title": "시황 속보",
        "desc": "Gemini 로 실시간 시황 리포트를 생성합니다.",
    },
    "diver": {
        "icon": "🔎",
        "title": "키워드 뉴스 분석",
        "desc": "네이버 뉴스 + Gemini 로 키워드를 심층 분석합니다.",
    },
    "dejavu": {
        "icon": "🕰️",
        "title": "과거 유사 패턴",
        "desc": "같은 종목의 닮은 과거 구간과 이후 수익률을 봅니다.",
    },
    "match": {
        "icon": "🧬",
        "title": "유사 종목 검색",
        "desc": "기준 종목과 닮은 다른 종목을 DTW 로 찾습니다.",
    },
}


def _render_home() -> None:
    st.title("📈 snapatch")
    st.caption("주식 속보·분석·유사도 검색 통합 플랫폼")
    st.write("")
    cols = st.columns(2)
    for idx, (key, meta) in enumerate(_FEATURES.items()):
        with cols[idx % 2]:
            with st.container(border=True):
                st.subheader(f"{meta['icon']} {key}")
                st.write(f"**{meta['title']}**")
                st.caption(meta["desc"])
    st.write("")
    st.info("왼쪽 사이드바에서 기능을 선택하세요.", icon="👈")


def main() -> None:
    with st.sidebar:
        st.title("📈 snapatch")
        options = ["홈", *_FEATURES.keys()]
        choice = st.radio(
            "기능 선택",
            options=options,
            format_func=lambda k: (
                "🏠 홈" if k == "홈"
                else f"{_FEATURES[k]['icon']} {k} — {_FEATURES[k]['title']}"
            ),
        )
        st.divider()
        st.caption("snapatch · breaker / diver / dejavu / match")

    if choice == "홈":
        _render_home()
        return

    if choice == "breaker":
        from snapatch.features import breaker

        breaker.render()
    elif choice == "diver":
        from snapatch.features import diver

        diver.render()
    elif choice == "dejavu":
        from snapatch.features import dejavu

        dejavu.render()
    elif choice == "match":
        from snapatch.features import match

        match.render()


if __name__ == "__main__":
    main()
