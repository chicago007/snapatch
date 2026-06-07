"""2차: 종가 min-max + FastDTW."""

from __future__ import annotations

import logging
from concurrent.futures import (
    ProcessPoolExecutor,
    ThreadPoolExecutor,
    as_completed,
)
from typing import Callable

from fastdtw import fastdtw
from scipy.spatial.distance import euclidean

from match.config import FormaConfig
from match.market_data import clean_data, get_stock_data

try:
    from tqdm import tqdm as _tqdm_iter
except ImportError:

    def _tqdm_iter(iterable, **_kwargs):
        return iterable


def normalize_close(df):
    s = df["종가"].astype(float)
    lo, hi = s.min(), s.max()
    if hi == lo:
        return s.values.reshape(-1, 1)
    return ((s - lo) / (hi - lo)).values.reshape(-1, 1)


def compute_dtw_distance(a, b) -> float:
    distance, _ = fastdtw(a, b, dist=euclidean)
    return float(distance)


def _process_ticker(args):
    ticker, target_series, start_date, end_date, min_data = args
    try:
        df = clean_data(get_stock_data(ticker, start_date, end_date))
        if len(df) < min_data:
            return ticker, float("inf")
        comp = normalize_close(df)
        return ticker, compute_dtw_distance(target_series, comp)
    except Exception as exc:  # noqa: BLE001
        print(f"Error processing {ticker}: {exc}")
        return ticker, float("inf")


def find_similar_by_close(
    target_df,
    tickers: list[str],
    cfg: FormaConfig,
    progress_cb: Callable[[int, int], None] | None = None,
) -> list[tuple[str, float]]:
    target_series = normalize_close(target_df)
    min_data = len(target_df)
    compare_start = cfg.compare_from or cfg.pattern_from
    compare_end = cfg.compare_to or cfg.pattern_to

    args = [
        (ticker, target_series, compare_start, compare_end, min_data)
        for ticker in tickers
    ]

    if cfg.use_threads_only:
        executor = ThreadPoolExecutor(max_workers=cfg.max_workers)
    else:
        try:
            executor = ProcessPoolExecutor(max_workers=cfg.max_workers)
        except (PermissionError, OSError) as exc:
            logging.warning(
                "ProcessPoolExecutor 불가 → ThreadPoolExecutor: %s",
                exc,
            )
            executor = ThreadPoolExecutor(max_workers=cfg.max_workers)

    results: list[tuple[str, float]] = []
    total = len(args)
    with executor:
        futures = [executor.submit(_process_ticker, a) for a in args]
        for done, fut in enumerate(
            _tqdm_iter(as_completed(futures), total=total),
            start=1,
        ):
            results.append(fut.result())
            if progress_cb is not None:
                progress_cb(done, total)

    finite = [(t, d) for t, d in results if d != float("inf")]
    finite.sort(key=lambda x: x[1])
    return finite[: cfg.top_n]
