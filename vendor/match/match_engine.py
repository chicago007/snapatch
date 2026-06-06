"""특정 종목·기간의 종가 패턴과 유사한 종목을 찾는 단순 엔진 (종가 전용).

설정만 바꾸면 됩니다: PATTERN_TICKER / PATTERN_FROM / PATTERN_TO,
필요하면 후보 비교 구간(COMPARE_FROM/COMPARE_TO).
유사도 산출 후 타겟·추천 종목 종가 차트를 한 PNG로 저장(SAVE_SIMILARITY_CHART).
"""

from __future__ import annotations

import logging
import math
import os
from concurrent.futures import (
    ProcessPoolExecutor,
    ThreadPoolExecutor,
    as_completed,
)
import sys
from pathlib import Path

import pandas as pd

_BASE_DIR = Path(__file__).resolve().parent
if str(_BASE_DIR) not in sys.path:
    sys.path.insert(0, str(_BASE_DIR))
from pandas.api.types import is_datetime64_any_dtype
from fastdtw import fastdtw
from scipy.spatial.distance import euclidean

from krx_io import (
    REQUEST_TIMEOUT_SEC,
    patch_requests_default_timeout,
    prompt_krx_login_if_needed,
)

# snapatch 통합: import 시점에 터미널 input()으로 블로킹되지 않도록
# 대화형 로그인 프롬프트를 생략한다. KRX 로그인은 Streamlit UI에서
# 환경변수(KRX_ID/KRX_PW)를 설정한 뒤 apply_krx_login()으로 적용한다.
patch_requests_default_timeout(REQUEST_TIMEOUT_SEC)


def apply_krx_login() -> bool:
    """환경변수 KRX_ID/KRX_PW 기반으로 KRX 세션을 적용한다(비대화형)."""
    import krx_io

    krx_io._login_ready = True
    login_id = (os.getenv("KRX_ID") or "").strip()
    login_pw = (os.getenv("KRX_PW") or "").strip()
    if login_id and login_pw:
        return krx_io._apply_krx_session(login_id, login_pw)
    return False

from pykrx import stock  # noqa: E402

logging.getLogger("pykrx").setLevel(logging.CRITICAL)
logging.getLogger("pykrx").propagate = False

_MPL = Path(__file__).resolve().parent / ".matplotlib-cache"
_MPL.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("MPLCONFIGDIR", str(_MPL))

try:
    from tqdm import tqdm as _tqdm_iter
except ImportError:

    def _tqdm_iter(iterable, **_kwargs):
        return iterable

# ----- 사용자 설정 -----
PATTERN_TICKER = "397030"
PATTERN_FROM = "20251103"
PATTERN_TO = "20260514"

COMPARE_FROM = PATTERN_FROM
COMPARE_TO = PATTERN_TO

TOP_N = 20
MAX_WORKERS = 4
USE_THREADS_ONLY = False
TICKER_CSV = Path(__file__).resolve().parent / "tickers.csv"
EXCLUDE_PATTERN_TICKER = True

# 유사도 결과 후 종가 차트(정규화 0~1, DTW와 동일 스케일)를 한 PNG로 저장.
SAVE_SIMILARITY_CHART = True
CHART_OUTPUT_PATH: Path | None = None  # None이면 스크립트 폴더에 자동 파일명
CHART_GRID_COLS = 3  # 열 수 ↓ → 패널 가로 넓게
CHART_PANEL_W = 5.2  # 열당 가로(인치)
CHART_PANEL_H = 3.6  # 행당 세로(인치)
CHART_TARGET_ROW_SCALE = 1.45  # 타겟 행 높이 배율
CHART_DPI = 140


def normalize_ticker(raw: str) -> str:
    return str(raw).strip().strip("'").zfill(6)


def get_stock_data(ticker, start_date, end_date):
    return stock.get_market_ohlcv_by_date(
        start_date,
        end_date,
        ticker,
    )


def clean_data(df):
    return df.dropna()


def normalize_close(df):
    s = df["종가"].astype(float)
    lo, hi = s.min(), s.max()
    if hi == lo:
        return s.values.reshape(-1, 1)
    return ((s - lo) / (hi - lo)).values.reshape(-1, 1)


def compute_dtw_distance(a, b):
    distance, _ = fastdtw(a, b, dist=euclidean)
    return distance


def process_ticker(args):
    ticker, target_series, start_date, end_date, min_data = args
    try:
        df = clean_data(get_stock_data(ticker, start_date, end_date))
        if len(df) < min_data:
            return ticker, float("inf")
        comp = normalize_close(df)
        return ticker, compute_dtw_distance(target_series, comp)
    except Exception as e:
        print(f"Error processing {ticker}: {e}")
        return ticker, float("inf")


def find_similar_by_close(
    target_df,
    compare_start,
    compare_end,
    tickers,
    top_n=TOP_N,
    max_workers=MAX_WORKERS,
    use_threads_only=USE_THREADS_ONLY,
):
    target_series = normalize_close(target_df)
    min_data = len(target_df)

    args = [
        (ticker, target_series, compare_start, compare_end, min_data)
        for ticker in tickers
    ]

    results = []
    if use_threads_only:
        executor = ThreadPoolExecutor(max_workers=max_workers)
    else:
        try:
            executor = ProcessPoolExecutor(max_workers=max_workers)
        except (PermissionError, OSError) as exc:
            logging.warning(
                "ProcessPoolExecutor를 사용할 수 없어 ThreadPoolExecutor로 대체: %s",
                exc,
            )
            executor = ThreadPoolExecutor(max_workers=max_workers)
    with executor:
        futures = [executor.submit(process_ticker, a) for a in args]
        for fut in _tqdm_iter(as_completed(futures), total=len(futures)):
            results.append(fut.result())

    finite = [(t, d) for t, d in results if d != float("inf")]
    finite.sort(key=lambda x: x[1])
    return finite[:top_n]


def read_tickers(csv_path):
    df = pd.read_csv(csv_path)
    return [normalize_ticker(x) for x in df["ticker"]]


def _norm_close_1d(df: pd.DataFrame) -> pd.Series:
    s = df["종가"].astype(float)
    lo, hi = float(s.min()), float(s.max())
    if hi <= lo:
        return pd.Series(0.5, index=s.index, dtype=float)
    return (s - lo) / (hi - lo)


def _default_chart_path(pattern_id: str) -> Path:
    base = Path(__file__).resolve().parent
    return base / f"close_similar_{pattern_id}_{PATTERN_FROM}_{PATTERN_TO}.png"


def _index_is_trading_dates(idx) -> bool:
    if isinstance(idx, pd.MultiIndex):
        return False
    if isinstance(idx, pd.DatetimeIndex):
        return True
    return bool(is_datetime64_any_dtype(idx))


def _plot_norm_on_ax(
    ax,
    y: pd.Series,
    *,
    color: str,
    linewidth: float,
    label: str | None = None,
    use_dates: bool = False,
) -> bool:
    """use_dates=True면 날짜 축(타겟용), False면 거래일 순번(좁은 패널용)."""
    if use_dates and _index_is_trading_dates(y.index):
        ax.plot(y.index, y.values, color=color, linewidth=linewidth, label=label)
        return True
    n = len(y)
    xs = range(n)
    ax.plot(xs, y.values, color=color, linewidth=linewidth, label=label)
    if n > 1:
        ax.set_xlim(0, n - 1)
    ax.set_xlabel("거래일", fontsize=7)
    return False


def save_close_similarity_chart(
    pattern_id: str,
    pattern_df: pd.DataFrame,
    compare_start: str,
    compare_end: str,
    hits: list[tuple[str, float]],
    out_path: Path,
) -> None:
    """타겟 1패널 + 추천 종목 각 패널. 종가는 구간 내 min-max 정규화(DTW 입력과 동일)."""
    try:
        import matplotlib.dates as mdates
        import matplotlib.pyplot as plt
    except ImportError:
        logging.warning(
            "matplotlib이 없어 차트를 생략합니다. 설치: pip install matplotlib",
        )
        return

    if not hits:
        logging.warning("추천 종목이 없어 차트를 생략합니다.")
        return

    ncol = max(1, int(CHART_GRID_COLS))
    n_rec = len(hits)
    n_row_rec = max(1, math.ceil(n_rec / ncol))
    n_rows = 1 + n_row_rec
    panel_w = float(CHART_PANEL_W)
    panel_h = float(CHART_PANEL_H)
    target_scale = float(CHART_TARGET_ROW_SCALE)
    fig_w = panel_w * ncol
    fig_h = panel_h * (target_scale + n_row_rec)
    fig = plt.figure(figsize=(fig_w, fig_h), layout="constrained")
    height_ratios = [target_scale] + [1.0] * n_row_rec
    gs = fig.add_gridspec(n_rows, ncol, height_ratios=height_ratios)

    ax0 = fig.add_subplot(gs[0, :])
    y0 = _norm_close_1d(pattern_df)
    is_dt0 = _plot_norm_on_ax(
        ax0,
        y0,
        color="black",
        linewidth=1.6,
        label="종가(정규화)",
        use_dates=True,
    )
    ax0.set_title(f"타겟 {pattern_id}  ({compare_start}~{compare_end})")
    ax0.set_ylabel("정규화 종가")
    ax0.set_ylim(-0.05, 1.05)
    ax0.grid(True, alpha=0.3)
    if is_dt0:
        ax0.xaxis.set_major_formatter(mdates.DateFormatter("%y-%m-%d"))
    ax0.legend(loc="upper right", fontsize=8)
    fig.suptitle(
        f"DTW 유사 종가 — 패턴 {pattern_id} / 추천 상위 {len(hits)}개",
        fontsize=12,
    )

    for i, (ticker, dist) in enumerate(hits):
        r = 1 + i // ncol
        c = i % ncol
        ax = fig.add_subplot(gs[r, c])
        try:
            cdf = clean_data(get_stock_data(ticker, compare_start, compare_end))
            if cdf.empty:
                ax.set_title(f"{ticker}\n(데이터 없음)")
                ax.axis("off")
                continue
            y = _norm_close_1d(cdf)
            _plot_norm_on_ax(ax, y, color="C0", linewidth=1.0, use_dates=False)
            ax.set_title(f"{ticker}\nDTW={dist:.4f}", fontsize=9)
            ax.set_ylim(-0.05, 1.05)
            ax.grid(True, alpha=0.25)
            ax.tick_params(labelsize=7)
        except Exception as exc:  # noqa: BLE001
            ax.set_title(f"{ticker}\n오류")
            ax.text(0.5, 0.5, str(exc), ha="center", va="center", fontsize=7)
            ax.axis("off")

    out_path = out_path.resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=CHART_DPI, bbox_inches="tight", pad_inches=0.25)
    plt.close(fig)
    print(f"차트 저장: {out_path}")


def main():
    tickers = read_tickers(TICKER_CSV)
    pattern_id = normalize_ticker(PATTERN_TICKER)

    if EXCLUDE_PATTERN_TICKER:
        tickers = [t for t in tickers if t != pattern_id]

    target_df = clean_data(get_stock_data(pattern_id, PATTERN_FROM, PATTERN_TO))
    if target_df.empty:
        raise SystemExit(
            f"패턴 구간에 데이터가 없습니다: {pattern_id} "
            f"{PATTERN_FROM}~{PATTERN_TO}",
        )

    print(
        f"패턴: {pattern_id} {PATTERN_FROM}~{PATTERN_TO} | "
        f"비교 구간: {COMPARE_FROM}~{COMPARE_TO} | "
        f"min_data={len(target_df)} | tickers={len(tickers)} | "
        f"use_threads_only={USE_THREADS_ONLY}",
    )

    hits = find_similar_by_close(
        target_df,
        COMPARE_FROM,
        COMPARE_TO,
        tickers,
    )

    print("(종가) 유사한 패턴을 가진 종목:")
    for rank, (ticker, dist) in enumerate(hits, start=1):
        print(f"{rank:2d}. {ticker}  dtw={dist:.4f}")

    if SAVE_SIMILARITY_CHART:
        chart_path = CHART_OUTPUT_PATH or _default_chart_path(pattern_id)
        save_close_similarity_chart(
            pattern_id,
            target_df,
            COMPARE_FROM,
            COMPARE_TO,
            hits,
            chart_path,
        )


if __name__ == "__main__":
    main()
