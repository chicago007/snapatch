"""dejavu — 같은 종목의 과거 유사 패턴 분석 (capstone001)."""

from __future__ import annotations

import io
from contextlib import redirect_stdout
from datetime import datetime
from pathlib import Path

import streamlit as st

from snapatch import bootstrap

bootstrap.init()

import dejavu00  # noqa: E402

_OUTPUT_BASE = bootstrap.project_root() / "outputs" / "dejavu"

_ALL_METHODS = ["pearson", "cosine", "euclidean", "manhattan", "spearman", "dtw"]


def _build_config(
    ticker: str,
    data_start: str,
    target_date: str,
    observation_days: int,
    top_n: int,
    forward_days: int,
    scan_step: int,
    methods: list[str],
    out_dir: Path,
) -> dict:
    return {
        "ticker": ticker,
        "data_start": data_start,
        "target_date": target_date or "today",
        "observation_days": observation_days,
        "top_n_similar": top_n,
        "forward_monitoring_days": forward_days,
        "similarity_scan_step_trading_days": scan_step,
        "similarity_scan_description": "유사 후보: 거래일 시작 간격 {step}일",
        "similarity_methods": methods,
        "use_dtw": "dtw" in methods,
        "output_dir": str(out_dir),
        "chart_filename_prefix": "pattern_comparison",
        "price_column": "종가",
        "chart_normalization": "index100",
        "save_table_csv": True,
        "save_table_txt": False,
        "save_table_md": False,
    }


def render() -> None:
    st.header("🕰️ dejavu — 과거 유사 패턴")
    st.caption("한 종목의 최근 관찰 구간과 닮은 과거 구간을 찾아 이후 수익률을 요약합니다.")

    c1, c2, c3 = st.columns(3)
    ticker = c1.text_input("종목 코드", value="005930", help="예: 005930 (삼성전자)")
    data_start = c2.text_input("데이터 시작일", value="20150101")
    target_date = c3.text_input("타겟 기준일", value="today", help="today 또는 YYYYMMDD")

    c4, c5, c6 = st.columns(3)
    observation_days = c4.number_input("관찰 거래일", min_value=5, max_value=250, value=60)
    forward_days = c5.number_input("이후 관찰일", min_value=1, max_value=120, value=20)
    top_n = c6.number_input("방법당 유사 구간 수", min_value=1, max_value=20, value=5)

    c7, c8 = st.columns(2)
    scan_step = c7.number_input("스캔 간격(거래일)", min_value=1, max_value=20, value=5)
    methods = c8.multiselect(
        "유사도 방법",
        options=_ALL_METHODS,
        default=["pearson", "euclidean"],
    )

    if not st.button("패턴 분석", type="primary", use_container_width=True):
        return
    if not ticker.strip():
        st.warning("종목 코드를 입력하세요.", icon="⚠️")
        return
    if not methods:
        st.warning("유사도 방법을 최소 1개 선택하세요.", icon="⚠️")
        return

    run_tag = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = _OUTPUT_BASE / f"{ticker.strip()}_{run_tag}"
    cfg = _build_config(
        ticker.strip(), data_start.strip(), target_date.strip(),
        int(observation_days), int(top_n), int(forward_days),
        int(scan_step), methods, out_dir,
    )

    with st.spinner("시세 조회 및 유사 패턴 분석 중..."):
        try:
            ctx = dejavu00.build_analysis_context(cfg, None)
            buf = io.StringIO()
            with redirect_stdout(buf):
                dejavu00.run_method_reports(ctx, None)
            console_log = buf.getvalue()
        except Exception as exc:  # noqa: BLE001
            st.error(f"분석 실패: {exc}", icon="🚫")
            return

    st.success("분석이 완료되었습니다.")

    pngs = sorted(out_dir.glob("*.png")) if out_dir.is_dir() else []
    if pngs:
        for png in pngs:
            st.image(str(png), caption=png.name, use_container_width=True)
    else:
        st.info("생성된 차트가 없습니다. 콘솔 로그를 확인하세요.", icon="ℹ️")

    with st.expander("분석 로그 보기", expanded=not pngs):
        st.text(console_log or "(출력 없음)")
