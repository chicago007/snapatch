"""1차: SAX + 특징 + 규칙 필터."""

from __future__ import annotations

import logging
from concurrent.futures import FIRST_COMPLETED, wait
from typing import Callable

import numpy as np
from scipy.stats import norm

ProgressCallback = Callable[[int, int], None]

from match.config import FormaConfig
from match.market_data import clean_data, close_series, get_stock_data

_SAX_BP_CACHE: dict[int, np.ndarray] = {}


def z_normalize(x: np.ndarray) -> np.ndarray:
    x = np.asarray(x, dtype=float)
    m, s = np.mean(x), np.std(x)
    if s < 1e-12:
        return np.zeros_like(x)
    return (x - m) / s


def paa(x: np.ndarray, segments: int) -> np.ndarray:
    L = len(x)
    if L < segments:
        raise ValueError("시계열이 PAA 구간 수보다 짧습니다.")
    out = np.zeros(segments)
    for i in range(segments):
        a = int(i * L / segments)
        b = max(int((i + 1) * L / segments), a + 1)
        out[i] = np.mean(x[a:b])
    return out


def _sax_breakpoints(alphabet: int) -> np.ndarray:
    if alphabet not in _SAX_BP_CACHE:
        _SAX_BP_CACHE[alphabet] = norm.ppf(
            np.linspace(1.0 / alphabet, 1.0 - 1.0 / alphabet, alphabet - 1),
        )
    return _SAX_BP_CACHE[alphabet]


def series_to_sax(x: np.ndarray, segments: int, alphabet: int) -> str:
    z = z_normalize(x)
    p = paa(z, segments)
    bps = _sax_breakpoints(alphabet)
    return "".join(
        chr(ord("a") + int(np.searchsorted(bps, v))) for v in p
    )


def sax_hamming(a: str, b: str) -> int:
    return sum(1 for u, v in zip(a, b) if u != v)


def log_returns(close: np.ndarray) -> np.ndarray:
    c = np.asarray(close, dtype=float)
    if len(c) < 2:
        return np.array([])
    return np.diff(np.log(c))


def pattern_metrics(close: np.ndarray) -> tuple[float, float]:
    r = log_returns(close)
    std = float(np.std(r)) if len(r) > 1 else 0.0
    rng = float((np.max(close) - np.min(close)) / (np.mean(close) + 1e-12))
    return std, rng


def rule_pass(
    pattern_close: np.ndarray,
    cand_close: np.ndarray,
    std_ratio: tuple[float, float],
    range_ratio: tuple[float, float],
) -> bool:
    ps, pr = pattern_metrics(pattern_close)
    cs, cr = pattern_metrics(cand_close)
    if ps < 1e-12:
        ps = 1e-12
    if pr < 1e-12:
        pr = 1e-12
    if not (std_ratio[0] <= cs / ps <= std_ratio[1]):
        return False
    if not (range_ratio[0] <= cr / pr <= range_ratio[1]):
        return False
    return True


def feature_vector(close: np.ndarray) -> np.ndarray:
    c = np.asarray(close, dtype=float)
    r = log_returns(c)
    if len(r) == 0:
        return np.zeros(8)
    mu, sd = float(np.mean(r)), float(np.std(r) + 1e-12)
    tot = float(c[-1] / c[0] - 1.0)
    rng = float((np.max(c) - np.min(c)) / (np.mean(c) + 1e-12))
    up = float(np.mean(r > 0))
    cum = np.cumprod(1.0 + r)
    dd = float(np.min(cum / np.maximum.accumulate(cum) - 1.0))
    absm = float(np.mean(np.abs(r)))
    sharpe = float(mu / sd)
    return np.array([mu, sd, tot, rng, up, dd, absm, sharpe], dtype=float)


def feature_l1_relative(pattern_f: np.ndarray, cand_f: np.ndarray) -> float:
    denom = np.abs(pattern_f) + 1e-8
    return float(np.sum(np.abs(cand_f - pattern_f) / denom))


def process_one(
    ticker: str,
    pattern_sax: str,
    pattern_feat: np.ndarray,
    pattern_close: np.ndarray,
    compare_start: str,
    compare_end: str,
    min_len: int,
    skip_rule: bool,
    rule_std_ratio: tuple[float, float],
    rule_range_ratio: tuple[float, float],
    sax_segments: int,
    sax_alphabet: int,
) -> tuple[str, str, int | None, float | None]:
    try:
        df = clean_data(get_stock_data(ticker, compare_start, compare_end))
        if len(df) < min_len:
            return ticker, "short", None, None
        c = close_series(df)
        if not skip_rule and not rule_pass(
            pattern_close,
            c,
            rule_std_ratio,
            rule_range_ratio,
        ):
            return ticker, "rule", None, None
        sax_c = series_to_sax(c, sax_segments, sax_alphabet)
        h = sax_hamming(pattern_sax, sax_c)
        fv = feature_vector(c)
        d = feature_l1_relative(pattern_feat, fv)
        return ticker, "ok", h, d
    except Exception as exc:  # noqa: BLE001
        print(f"Error {ticker}: {exc}")
        return ticker, "err", None, None


def _print_parallel_diagnostic(
    title: str,
    fut_to_ticker: dict,
    pending: set,
    completed: int,
    total: int,
) -> None:
    waiting = [fut_to_ticker[f] for f in pending]
    print("\n" + "=" * 64, flush=True)
    print(f"[진단] {title}", flush=True)
    print(f"  완료된 작업: {completed} / 전체 {total}", flush=True)
    print(f"  아직 끝나지 않은 작업: {len(pending)}", flush=True)
    if waiting:
        head = waiting[:50]
        tail = f" … 외 {len(waiting) - 50}개" if len(waiting) > 50 else ""
        print(f"  대기 중 티커(최대 50개): {', '.join(head)}{tail}", flush=True)
    print("=" * 64 + "\n", flush=True)


def _make_progress_bar(total: int):
    try:
        from tqdm import tqdm

        return tqdm(total=total, desc="tickers", leave=True)
    except ImportError:
        return None


def collect_parallel_results(
    fut_to_ticker: dict,
    heartbeat_sec: float,
    progress_cb: ProgressCallback | None = None,
) -> tuple[list[tuple[str, int, float]], int, int, int]:
    pending = set(fut_to_ticker.keys())
    total = len(pending)
    completed = 0
    passed: list[tuple[str, int, float]] = []
    too_short = failed_rule = errors = 0
    pbar = _make_progress_bar(total)

    try:
        while pending:
            timeout = None if heartbeat_sec <= 0 else float(heartbeat_sec)
            try:
                done, pending = wait(
                    pending,
                    timeout=timeout,
                    return_when=FIRST_COMPLETED,
                )
            except KeyboardInterrupt:
                _print_parallel_diagnostic(
                    "사용자 중단 (Ctrl+C)",
                    fut_to_ticker,
                    pending,
                    completed,
                    total,
                )
                raise

            if not done:
                _print_parallel_diagnostic(
                    f"{heartbeat_sec:.0f}초 동안 새로 완료된 작업 없음",
                    fut_to_ticker,
                    pending,
                    completed,
                    total,
                )
                continue

            for fut in done:
                try:
                    ticker, status, h, d = fut.result()
                except Exception as exc:  # noqa: BLE001
                    errors += 1
                    logging.warning("Future 예외: %s", exc)
                else:
                    if status == "short":
                        too_short += 1
                    elif status == "rule":
                        failed_rule += 1
                    elif status == "err":
                        errors += 1
                    elif h is not None and d is not None:
                        passed.append((ticker, h, d))

                if pbar:
                    pbar.update(1)
                completed += 1
                if progress_cb is not None:
                    progress_cb(completed, total)
    finally:
        if pbar:
            pbar.close()

    return passed, too_short, failed_rule, errors


def rank_stage1(
    passed: list[tuple[str, int, float]],
    cfg: FormaConfig,
) -> list[tuple[str, float]]:
    if not passed:
        return []

    if cfg.stage1_rank_by == "sax":
        return sorted([(t, float(h)) for t, h, _ in passed], key=lambda x: x[1])

    if cfg.stage1_rank_by == "feat":
        return sorted([(t, float(d)) for t, _, d in passed], key=lambda x: x[1])

    w_sum = cfg.combined_sax_weight + cfg.combined_feat_weight
    if w_sum <= 0:
        raise ValueError("combined_sax_weight + combined_feat_weight > 0")

    ws = cfg.combined_sax_weight / w_sum
    wf = cfg.combined_feat_weight / w_sum
    hs = np.array([h for _, h, _ in passed], dtype=float)
    ds = np.array([d for _, _, d in passed], dtype=float)
    hn = (hs - hs.min()) / (hs.max() - hs.min() + 1e-12)
    dn = (ds - ds.min()) / (ds.max() - ds.min() + 1e-12)
    combined = [
        (passed[i][0], float(ws * hn[i] + wf * dn[i]))
        for i in range(len(passed))
    ]
    combined.sort(key=lambda x: x[1])
    return combined
