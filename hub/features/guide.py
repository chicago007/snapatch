"""snapatch 사용 설명서 — 웹 UI 전용 (WEB_USER_GUIDE.md)."""

from __future__ import annotations

import streamlit as st

from hub.paths import project_root
from hub.runtime import is_streamlit_cloud

_WEB_GUIDE = project_root() / "docs" / "WEB_USER_GUIDE.md"
_LOCAL_GUIDE = project_root() / "docs" / "USER_GUIDE.md"


def render() -> None:
    st.header("📖 사용 설명서")
    st.caption("브라우저에서 바로 쓰는 방법 (API 키·설치 불필요)")

    st.info(
        "웹에서는 **API 키 입력이 필요 없습니다.** "
        "분석 결과는 **다운로드 버튼**으로 저장하세요. "
        + (
            "서버에 `outputs` 폴더는 없습니다."
            if is_streamlit_cloud()
            else "로컬 웹 실행 시에도 **다운로드**로 저장하는 것을 권장합니다."
        ),
        icon="ℹ️",
    )

    if not _WEB_GUIDE.is_file():
        st.error(
            f"웹 사용 설명서를 찾을 수 없습니다: `{_WEB_GUIDE}`",
            icon="🚫",
        )
        return

    content = _WEB_GUIDE.read_text(encoding="utf-8")
    st.markdown(content, unsafe_allow_html=False)

    st.download_button(
        "Markdown 다운로드",
        data=content.encode("utf-8"),
        file_name="snapatch_WEB_USER_GUIDE.md",
        mime="text/markdown",
        use_container_width=True,
        key="dl_user_guide",
    )

    if _LOCAL_GUIDE.is_file():
        with st.expander("로컬 · CLI 설치 안내 (개발자용)", expanded=False):
            st.markdown(_LOCAL_GUIDE.read_text(encoding="utf-8"))
