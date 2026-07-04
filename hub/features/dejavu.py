"""dejavu — 같은 종목의 과거 유사 패턴 분석 (capstone001)."""

from __future__ import annotations

import io
import time
from contextlib import redirect_stdout
from datetime import datetime
from pathlib import Path
from typing import Any

import streamlit as st

from hub import bootstrap

bootstrap.init()

from engines.dejavu import dejavu  # noqa: E402

_OUTPUT_BASE = bootstrap.dejavu_output_dir()

_TRACK_OPTIONS = {
    spec.key: spec.label for spec in dejavu.TRACK_SPECS
}


def _format_elapsed(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.1f}초"
    minutes = int(seconds // 60)
    remainder = seconds % 60
    return f"{minutes}분 {remainder:.1f}초"


def _build_config(
    ticker: str,
    data_start: str,
    target_date: str,
    observation_days: int,
    top_n: int,
    forward_days: int,
    scan_step: int,
    tracks: dict[str, bool],
    ma_windows: list[int],
    out_dir: Path,
    *,
    save_csv: bool = True,
    save_txt: bool = True,
    save_md: bool = True,
) -> dict[str, Any]:
    return {
        "ticker": ticker,
        "data_start": data_start,
        "target_date": target_date or "today",
        "observation_days": observation_days,
        "top_n_similar": top_n,
        "forward_monitoring_days": forward_days,
        "similarity_scan_step_trading_days": scan_step,
        "similarity_scan_description": "유사 후보: 거래일 시작 간격 {step}일",
        "similarity_methods": ["pearson", "dtw"],
        "use_dtw": True,
        "pipeline_dejavu": {
            "enabled": True,
            "emit_tracks": True,
            "ma_windows": ma_windows,
            "tracks": tracks,
        },
        "output_dir": str(out_dir),
        "chart_filename_prefix": "pattern_comparison_dejavu",
        "price_column": "종가",
        "save_table_csv": save_csv,
        "save_table_txt": save_txt,
        "save_table_md": save_md,
    }


def _run_analysis(raw: dict[str, Any]) -> tuple[Path, str]:
    """설정 dict로 dejavu 파이프라인 실행. (출력 디렉터리, 콘솔 로그)"""
    buf = io.StringIO()
    with redirect_stdout(buf):
        dejavu.configure_stdio_utf8()
        pipe = dejavu.parse_pipeline_config(raw)
        if not pipe.enabled:
            raise ValueError("pipeline_dejavu.enabled 가 false 입니다.")
        ctx = dejavu.build_run_context(raw, pipe)
        dejavu._print_target_header(ctx, pipe)
        outcome = dejavu.run_pipeline(ctx, pipe)
        if outcome is None:
            raise ValueError(
                "활성 트랙이 없습니다. 트랙 선택 또는 use_dtw 설정을 확인하세요.",
            )
        dejavu.write_result_documents(ctx, pipe, outcome)
    return ctx.out_dir, buf.getvalue()


def render() -> None:
    st.header("🕰️ dejavu — 과거 유사 패턴")
    st.caption(
        "6트랙 독립 분석 (주가 z / 로그수익률 / MA z × Pearson·DTW). "
        "관찰 구간과 닮은 과거 구간의 이후 수익률을 요약합니다.",
    )

    c1, c2, c3 = st.columns(3)
    ticker = c1.text_input("종목 코드", value="005930", help="예: 005930 (삼성전자)")
    data_start = c2.text_input("데이터 시작일", value="20150101")
    target_date = c3.text_input("타겟 기준일", value="today", help="today 또는 YYYYMMDD")

    c4, c5, c6 = st.columns(3)
    observation_days = c4.number_input("관찰 거래일", min_value=5, max_value=250, value=60)
    forward_days = c5.number_input("이후 관찰일", min_value=1, max_value=120, value=20)
    top_n = c6.number_input("트랙당 유사 구간 수", min_value=1, max_value=20, value=5)

    c7, c8 = st.columns(2)
    scan_step = c7.number_input("스캔 간격(거래일)", min_value=1, max_value=20, value=10)
    ma_windows = c8.multiselect(
        "MA 기간 (3-x 트랙)",
        options=[5, 10, 20, 30, 60],
        default=[5, 10, 20],
    )

    enabled_tracks = st.multiselect(
        "활성 트랙",
        options=list(_TRACK_OPTIONS.keys()),
        default=list(_TRACK_OPTIONS.keys()),
        format_func=lambda k: _TRACK_OPTIONS[k],
    )
    c9, c10, c11 = st.columns(3)
    save_csv = c9.checkbox("CSV 표 저장", value=False)
    save_txt = c10.checkbox("TXT 결과문서", value=False)
    save_md = c11.checkbox("MD 결과문서", value=True)

    if not st.button("패턴 분석", type="primary", use_container_width=True):
        return
    if not ticker.strip():
        st.warning("종목 코드를 입력하세요.", icon="⚠️")
        return
    if not enabled_tracks:
        st.warning("활성 트랙을 최소 1개 선택하세요.", icon="⚠️")
        return
    if not ma_windows and any(
        k.startswith("ma_zscore") for k in enabled_tracks
    ):
        st.warning("MA 트랙 사용 시 MA 기간을 선택하세요.", icon="⚠️")
        return

    tracks = {key: key in enabled_tracks for key in _TRACK_OPTIONS}
    run_tag = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = _OUTPUT_BASE / f"{ticker.strip()}_{run_tag}"
    raw = _build_config(
        ticker.strip(),
        data_start.strip(),
        target_date.strip(),
        int(observation_days),
        int(top_n),
        int(forward_days),
        int(scan_step),
        tracks,
        list(ma_windows),
        out_dir,
        save_csv=save_csv,
        save_txt=save_txt,
        save_md=save_md,
    )

    started_at = time.perf_counter()
    with st.spinner("시세 조회 및 6트랙 유사 패턴 분석 중..."):
        try:
            result_dir, console_log = _run_analysis(raw)
        except Exception as exc:  # noqa: BLE001
            st.error(f"분석 실패: {exc}", icon="🚫")
            return
    elapsed = time.perf_counter() - started_at

    st.success(
        f"분석이 완료되었습니다. (소요: {_format_elapsed(elapsed)}) 결과: `{result_dir}`",
    )

    pngs = sorted(result_dir.glob("*.png")) if result_dir.is_dir() else []
    if pngs:
        for png in pngs:
            st.image(str(png), caption=png.name, use_container_width=True)
    else:
        st.info("생성된 차트가 없습니다. 콘솔 로그를 확인하세요.", icon="ℹ️")

    if result_dir.is_dir():
        csvs = sorted(result_dir.glob("table_*.csv"))
        txts = sorted(result_dir.glob("results_tables_dejavu_*.txt"))
        mds = sorted(result_dir.glob("results_tables_dejavu_*.md"))
        if csvs or txts or mds:
            with st.expander("표·결과문서 다운로드", expanded=False):
                for path in csvs + txts + mds:
                    mime = (
                        "text/csv"
                        if path.suffix == ".csv"
                        else "text/markdown" if path.suffix == ".md" else "text/plain"
                    )
                    st.download_button(
                        label=f"다운로드: {path.name}",
                        data=path.read_bytes(),
                        file_name=path.name,
                        mime=mime,
                        key=f"dl_{path.name}",
                    )

    with st.expander("분석 로그 보기", expanded=not pngs):
        st.text(console_log or "(출력 없음)")
