"""Match 메인 — 1차(SAX) + 2차(DTW)."""

from __future__ import annotations

import logging
import time
from concurrent.futures import Executor, ProcessPoolExecutor, ThreadPoolExecutor
from typing import Callable

from match.chart import save_similarity_chart
from match.config import FormaConfig
from match.dtw import find_similar_by_close
from match.krx_io import patch_requests_default_timeout, prompt_krx_login_if_needed
from match.market_data import (
    clean_data,
    close_series,
    get_stock_data,
    normalize_ticker,
    read_tickers,
)
from match.stage1 import (
    collect_parallel_results,
    feature_vector,
    process_one,
    rank_stage1,
    series_to_sax,
)

# ----- 사용자 설정 -----
CONFIG = FormaConfig()


def _make_executor(cfg: FormaConfig) -> Executor:
    if cfg.use_threads_only:
        return ThreadPoolExecutor(max_workers=cfg.max_workers)
    try:
        return ProcessPoolExecutor(max_workers=cfg.max_workers)
    except (PermissionError, OSError) as exc:
        logging.warning(
            "ProcessPoolExecutor 불가 → ThreadPoolExecutor: %s",
            exc,
        )
        return ThreadPoolExecutor(max_workers=cfg.max_workers)


def _run_stage1(
    tickers: list[str],
    pattern_sax: str,
    pattern_feat,
    pattern_close,
    min_len: int,
    cfg: FormaConfig,
    progress_cb: Callable[[int, int], None] | None = None,
) -> tuple[list[str], list[tuple[str, int, float]], int, int, int]:
    compare_from = cfg.compare_from or cfg.pattern_from
    compare_to = cfg.compare_to or cfg.pattern_to

    with _make_executor(cfg) as executor:
        fut_to_ticker = {
            executor.submit(
                process_one,
                t,
                pattern_sax,
                pattern_feat,
                pattern_close,
                compare_from,
                compare_to,
                min_len,
                cfg.skip_rule_filter,
                cfg.rule_std_ratio,
                cfg.rule_range_ratio,
                cfg.sax_segments,
                cfg.sax_alphabet,
            ): t
            for t in tickers
        }
        passed, too_short, failed_rule, errors = collect_parallel_results(
            fut_to_ticker,
            cfg.heartbeat_sec,
            progress_cb,
        )

    ranked = rank_stage1(passed, cfg)
    k = min(cfg.stage1_top_k, len(ranked))
    stage1_tickers = [t for t, _ in ranked[:k]]
    return stage1_tickers, passed, too_short, failed_rule, errors


def _format_elapsed(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.1f}초"
    minutes = int(seconds // 60)
    remainder = seconds % 60
    return f"{minutes}분 {remainder:.1f}초"


def main(cfg: FormaConfig | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    cfg = cfg or CONFIG
    started_at = time.perf_counter()

    prompt_krx_login_if_needed()
    patch_requests_default_timeout(cfg.request_timeout_sec)

    tickers = read_tickers(cfg.ticker_csv)
    pattern_id = normalize_ticker(cfg.pattern_ticker)
    if cfg.exclude_pattern_ticker:
        tickers = [t for t in tickers if t != pattern_id]

    target_df = clean_data(
        get_stock_data(cfg.pattern_id, cfg.pattern_from, cfg.pattern_to),
    )
    if target_df.empty:
        raise SystemExit(
            f"패턴 구간 데이터 없음: {pattern_id} "
            f"{cfg.pattern_from}~{cfg.pattern_to}",
        )

    pattern_close = close_series(target_df)
    min_len = len(pattern_close)
    if min_len < cfg.sax_segments:
        raise SystemExit(
            f"패턴 길이({min_len}) < SAX segments({cfg.sax_segments})",
        )

    pattern_sax = series_to_sax(
        pattern_close,
        cfg.sax_segments,
        cfg.sax_alphabet,
    )
    pattern_feat = feature_vector(pattern_close)

    pool = "thread" if cfg.use_threads_only else "process(실패 시 thread)"
    print(
        f"[Match] 패턴 {pattern_id} "
        f"{cfg.pattern_from}~{cfg.pattern_to} | "
        f"비교 {cfg.compare_from}~{cfg.compare_to} | SAX={pattern_sax!r} | "
        f"후보 {len(tickers)} | 1차→DTW {cfg.stage1_top_k}→{cfg.top_n} | "
        f"1차={cfg.stage1_rank_by} | pool={pool} workers={cfg.max_workers}",
        flush=True,
    )

    stage1_tickers, passed, too_short, failed_rule, errors = _run_stage1(
        tickers,
        pattern_sax,
        pattern_feat,
        pattern_close,
        min_len,
        cfg,
    )

    print(
        f"1차 통과 {len(passed)} | 길이부족 {too_short} | "
        f"규칙탈락 {failed_rule} | 오류 {errors} | "
        f"DTW 대상 {len(stage1_tickers)}",
        flush=True,
    )

    if not stage1_tickers:
        print(
            "DTW 후보 없음. RULE 범위 확대 또는 skip_rule_filter=True 확인.",
        )
        return

    if cfg.stage1_preview > 0:
        preview = rank_stage1(passed, cfg)[: cfg.stage1_preview]
        print(f"\n1차 미리보기 ({cfg.stage1_rank_by}):")
        for i, (t, score) in enumerate(preview, 1):
            print(f"  {i:2d}. {t}  score={score:.4f}")

    print(f"\n2차 DTW (후보 {len(stage1_tickers)}개) …", flush=True)
    hits = find_similar_by_close(target_df, stage1_tickers, cfg)

    print(f"\n최종 TOP_{cfg.top_n} (DTW, 낮을수록 유사):")
    for rank, (ticker, dist) in enumerate(hits, start=1):
        print(f"  {rank:2d}. {ticker}  dtw={dist:.4f}")

    if cfg.save_similarity_chart:
        save_similarity_chart(
            pattern_id,
            target_df,
            hits,
            cfg.default_chart_path(),
            cfg,
        )

    print(f"\n소요 시간: {_format_elapsed(time.perf_counter() - started_at)}")


if __name__ == "__main__":
    main()
