"""match — 비슷한 패턴의 다른 종목 검색 (capstone002 / DTW)."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from snapatch import bootstrap

bootstrap.init()

import match_engine  # noqa: E402

_OUTPUT_BASE = bootstrap.project_root() / "outputs" / "match"


def _apply_login(krx_id: str, krx_pw: str) -> None:
    if krx_id and krx_pw:
        os.environ["KRX_ID"] = krx_id
        os.environ["KRX_PW"] = krx_pw
        match_engine.apply_krx_login()


def render() -> None:
    st.header("🧬 match — 유사 종목 검색")
    st.caption("기준 종목의 종가 패턴과 가장 닮은 다른 종목을 DTW 로 찾습니다.")

    with st.expander("KRX 로그인 (선택 · pykrx data.krx 조회)", expanded=False):
        lc1, lc2 = st.columns(2)
        krx_id = lc1.text_input("KRX 아이디", value=os.getenv("KRX_ID", ""))
        krx_pw = lc2.text_input("KRX 비밀번호", value="", type="password")

    c1, c2, c3 = st.columns(3)
    pattern_ticker = c1.text_input("기준 종목 코드", value="005930")
    pattern_from = c2.text_input("기간 시작", value="20240101", help="YYYYMMDD")
    pattern_to = c3.text_input("기간 종료", value="20241231", help="YYYYMMDD")

    c4, c5, c6 = st.columns(3)
    top_n = c4.number_input("상위 N개", min_value=1, max_value=50, value=20)
    max_workers = c5.number_input("동시 처리 수", min_value=1, max_value=16, value=4)
    exclude_self = c6.toggle("기준 종목 제외", value=True)

    csv_path = Path(match_engine.TICKER_CSV)
    try:
        n_tickers = len(pd.read_csv(csv_path))
        st.caption(f"후보 종목 목록: `{csv_path.name}` ({n_tickers}개)")
    except Exception:  # noqa: BLE001
        st.caption(f"후보 종목 목록: `{csv_path}`")

    if not st.button("유사 종목 검색", type="primary", use_container_width=True):
        return
    if not pattern_ticker.strip():
        st.warning("기준 종목 코드를 입력하세요.", icon="⚠️")
        return

    _apply_login(krx_id.strip(), krx_pw.strip())

    with st.spinner("기준 종목 시세 조회 중..."):
        try:
            pattern_id = match_engine.normalize_ticker(pattern_ticker.strip())
            tickers = match_engine.read_tickers(csv_path)
            if exclude_self:
                tickers = [t for t in tickers if t != pattern_id]
            target_df = match_engine.clean_data(
                match_engine.get_stock_data(
                    pattern_id, pattern_from.strip(), pattern_to.strip()
                )
            )
        except Exception as exc:  # noqa: BLE001
            st.error(f"기준 종목 조회 실패: {exc}", icon="🚫")
            return

    if target_df.empty:
        st.error(
            f"기준 구간에 데이터가 없습니다: {pattern_id} "
            f"{pattern_from}~{pattern_to}",
            icon="🚫",
        )
        return

    with st.spinner(f"{len(tickers)}개 종목과 DTW 유사도 계산 중..."):
        try:
            hits = match_engine.find_similar_by_close(
                target_df,
                pattern_from.strip(),
                pattern_to.strip(),
                tickers,
                top_n=int(top_n),
                max_workers=int(max_workers),
                use_threads_only=True,
            )
        except Exception as exc:  # noqa: BLE001
            st.error(f"유사도 계산 실패: {exc}", icon="🚫")
            return

    if not hits:
        st.warning("유사한 종목을 찾지 못했습니다.", icon="⚠️")
        return

    st.success(f"상위 {len(hits)}개 유사 종목을 찾았습니다.")

    result_df = pd.DataFrame(
        [{"순위": i, "종목코드": t, "DTW거리": round(d, 4)}
         for i, (t, d) in enumerate(hits, start=1)]
    )
    st.dataframe(result_df, use_container_width=True, hide_index=True)

    run_tag = datetime.now().strftime("%Y%m%d_%H%M%S")
    _OUTPUT_BASE.mkdir(parents=True, exist_ok=True)
    chart_path = _OUTPUT_BASE / f"close_similar_{pattern_id}_{run_tag}.png"
    with st.spinner("비교 차트 생성 중..."):
        try:
            match_engine.save_close_similarity_chart(
                pattern_id,
                target_df,
                pattern_from.strip(),
                pattern_to.strip(),
                hits,
                chart_path,
            )
        except Exception as exc:  # noqa: BLE001
            st.warning(f"차트 생성 실패: {exc}", icon="⚠️")
            chart_path = None

    if chart_path and chart_path.is_file():
        st.image(str(chart_path), caption=chart_path.name, use_container_width=True)
