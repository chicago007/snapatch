"""match — 2단계(SAX + DTW) 유사 종목 검색 (capstone002)."""

from __future__ import annotations

import io
import os
import time
from contextlib import redirect_stdout
from datetime import datetime
from pathlib import Path
from typing import Callable

import pandas as pd
import streamlit as st

from hub import bootstrap

bootstrap.init()

from match.chart import save_similarity_chart  # noqa: E402
from match.config import FormaConfig, resolve_ticker_csv  # noqa: E402
from match.dtw import find_similar_by_close  # noqa: E402
from match.krx_io import (  # noqa: E402
    apply_krx_login,
    patch_requests_default_timeout,
)
from match.main import _run_stage1  # noqa: E402
from match.market_data import (  # noqa: E402
    clean_data,
    close_series,
    get_stock_data,
    normalize_ticker,
    read_tickers,
)
from match.stage1 import feature_vector, series_to_sax  # noqa: E402

_OUTPUT_BASE = bootstrap.match_output_dir()

ProgressCallback = Callable[[int, int], None]


def _format_elapsed(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.1f}초"
    minutes = int(seconds // 60)
    remainder = seconds % 60
    return f"{minutes}분 {remainder:.1f}초"


def _apply_login(krx_id: str, krx_pw: str) -> None:
    if krx_id and krx_pw:
        os.environ["KRX_ID"] = krx_id
        os.environ["KRX_PW"] = krx_pw
        apply_krx_login()


def _run_match(
    cfg: FormaConfig,
    stage1_cb: ProgressCallback | None = None,
    dtw_cb: ProgressCallback | None = None,
) -> tuple[list[tuple[str, float]], Path | None, str]:
    """FormaConfig 로 1차(SAX)+2차(DTW) 실행. (hits, chart_path, log)."""
    patch_requests_default_timeout(cfg.request_timeout_sec)

    tickers = read_tickers(cfg.ticker_csv)
    pattern_id = cfg.pattern_id
    if cfg.exclude_pattern_ticker:
        tickers = [t for t in tickers if t != pattern_id]

    target_df = clean_data(
        get_stock_data(pattern_id, cfg.pattern_from, cfg.pattern_to),
    )
    if target_df.empty:
        raise ValueError(
            f"패턴 구간 데이터 없음: {pattern_id} "
            f"{cfg.pattern_from}~{cfg.pattern_to}",
        )

    pattern_close = close_series(target_df)
    min_len = len(pattern_close)
    if min_len < cfg.sax_segments:
        raise ValueError(
            f"패턴 길이({min_len}) < SAX segments({cfg.sax_segments})",
        )

    pattern_sax = series_to_sax(
        pattern_close,
        cfg.sax_segments,
        cfg.sax_alphabet,
    )
    pattern_feat = feature_vector(pattern_close)

    buf = io.StringIO()
    with redirect_stdout(buf):
        stage1_tickers, passed, too_short, failed_rule, errors = _run_stage1(
            tickers,
            pattern_sax,
            pattern_feat,
            pattern_close,
            min_len,
            cfg,
            progress_cb=stage1_cb,
        )
        print(
            f"1차 통과 {len(passed)} | 길이부족 {too_short} | "
            f"규칙탈락 {failed_rule} | 오류 {errors} | "
            f"DTW 대상 {len(stage1_tickers)}",
        )

        if not stage1_tickers:
            print("DTW 후보 없음.")
            return [], None, buf.getvalue()

        hits = find_similar_by_close(
            target_df,
            stage1_tickers,
            cfg,
            progress_cb=dtw_cb,
        )
        for rank, (ticker, dist) in enumerate(hits, start=1):
            print(f"  {rank:2d}. {ticker}  dtw={dist:.4f}")

        chart_path: Path | None = None
        if cfg.save_similarity_chart and hits:
            chart_path = cfg.chart_output_path or cfg.default_chart_path()
            save_similarity_chart(
                pattern_id,
                target_df,
                hits,
                chart_path,
                cfg,
            )

    return hits, chart_path, buf.getvalue()


def render() -> None:
    st.header("🧬 match — 유사 종목 검색")
    st.caption(
        "1차 SAX·특징 필터 → 2차 FastDTW. "
        "기준 종목 종가 패턴과 닮은 다른 종목을 찾습니다.",
    )

    with st.expander("KRX 로그인 (선택 · pykrx data.krx 조회)", expanded=False):
        lc1, lc2 = st.columns(2)
        krx_id = lc1.text_input("KRX 아이디", value=os.getenv("KRX_ID", ""))
        krx_pw = lc2.text_input("KRX 비밀번호", value="", type="password")

    c1, c2, c3 = st.columns(3)
    pattern_ticker = c1.text_input("기준 종목 코드", value="005930")
    pattern_from = c2.text_input("기간 시작", value="20240101", help="YYYYMMDD")
    pattern_to = c3.text_input("기간 종료", value="20241231", help="YYYYMMDD")

    c4, c5, c6 = st.columns(3)
    top_n = c4.number_input("최종 TOP N (DTW)", min_value=1, max_value=50, value=20)
    stage1_top_k = c5.number_input(
        "1차→DTW 후보 수",
        min_value=10,
        max_value=200,
        value=60,
        help="SAX 1차 필터 통과 후 DTW에 넘길 종목 수",
    )
    max_workers = c6.number_input("동시 처리 수", min_value=1, max_value=16, value=4)

    c7, c8 = st.columns(2)
    ticker_source = c7.selectbox(
        "후보 종목 CSV",
        options=["uni.csv", "tickers.csv"],
        index=0,
    )
    exclude_self = c8.toggle("기준 종목 제외", value=True)

    csv_path = resolve_ticker_csv(ticker_source)
    try:
        n_tickers = len(read_tickers(csv_path))
        st.caption(f"후보 종목: `{csv_path.name}` ({n_tickers}개)")
    except Exception:  # noqa: BLE001
        st.caption(f"후보 종목: `{csv_path}`")

    if not st.button("유사 종목 검색", type="primary", use_container_width=True):
        return
    if not pattern_ticker.strip():
        st.warning("기준 종목 코드를 입력하세요.", icon="⚠️")
        return

    _apply_login(krx_id.strip(), krx_pw.strip())

    run_tag = datetime.now().strftime("%Y%m%d_%H%M%S")
    pattern_id = normalize_ticker(pattern_ticker.strip())
    _OUTPUT_BASE.mkdir(parents=True, exist_ok=True)
    chart_path = _OUTPUT_BASE / f"match_{pattern_id}_{run_tag}.png"

    cfg = FormaConfig(
        pattern_ticker=pattern_id,
        pattern_from=pattern_from.strip(),
        pattern_to=pattern_to.strip(),
        top_n=int(top_n),
        stage1_top_k=int(stage1_top_k),
        max_workers=int(max_workers),
        use_threads_only=True,
        ticker_csv=csv_path,
        exclude_pattern_ticker=exclude_self,
        save_similarity_chart=True,
        chart_output_path=chart_path,
    )

    prog_stage1 = st.progress(0.0, text="1차 SAX 필터 준비 중...")
    prog_dtw = st.progress(0.0, text="2차 DTW 대기 중...")

    def _stage1_cb(done: int, total: int) -> None:
        ratio = done / total if total else 1.0
        prog_stage1.progress(ratio, text=f"1차 SAX 필터 {done}/{total}")

    def _dtw_cb(done: int, total: int) -> None:
        ratio = done / total if total else 1.0
        prog_dtw.progress(ratio, text=f"2차 DTW {done}/{total}")

    started_at = time.perf_counter()
    try:
        hits, saved_chart, console_log = _run_match(cfg, _stage1_cb, _dtw_cb)
    except Exception as exc:  # noqa: BLE001
        st.error(f"검색 실패: {exc}", icon="🚫")
        return
    elapsed = time.perf_counter() - started_at

    prog_stage1.empty()
    prog_dtw.empty()

    if not hits:
        st.warning(
            f"유사한 종목을 찾지 못했습니다. (소요: {_format_elapsed(elapsed)})",
            icon="⚠️",
        )
        with st.expander("분석 로그"):
            st.text(console_log or "(출력 없음)")
        return

    st.success(
        f"상위 {len(hits)}개 유사 종목을 찾았습니다. "
        f"(소요: {_format_elapsed(elapsed)})",
    )

    result_df = pd.DataFrame(
        [{"순위": i, "종목코드": t, "DTW거리": round(d, 4)}
         for i, (t, d) in enumerate(hits, start=1)]
    )
    st.dataframe(result_df, use_container_width=True, hide_index=True)

    if saved_chart and saved_chart.is_file():
        st.image(str(saved_chart), caption=saved_chart.name, use_container_width=True)

    with st.expander("분석 로그 보기", expanded=False):
        st.text(console_log or "(출력 없음)")
