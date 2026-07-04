"""유사도 결과 차트 PNG."""

from __future__ import annotations

import logging
import math
import os
from pathlib import Path

import pandas as pd
from pandas.api.types import is_datetime64_any_dtype

from .config import FormaConfig
from .market_data import clean_data, get_stock_data

_PKG = Path(__file__).resolve().parent
_MPL = _PKG / ".matplotlib-cache"
_MPL.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("MPLCONFIGDIR", str(_MPL))


def _norm_close_1d(df: pd.DataFrame) -> pd.Series:
    s = df["종가"].astype(float)
    lo, hi = float(s.min()), float(s.max())
    if hi <= lo:
        return pd.Series(0.5, index=s.index, dtype=float)
    return (s - lo) / (hi - lo)


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
    if use_dates and _index_is_trading_dates(y.index):
        ax.plot(y.index, y.values, color=color, linewidth=linewidth, label=label)
        return True
    n = len(y)
    ax.plot(range(n), y.values, color=color, linewidth=linewidth, label=label)
    if n > 1:
        ax.set_xlim(0, n - 1)
    ax.set_xlabel("거래일", fontsize=7)
    return False


def save_similarity_chart(
    pattern_id: str,
    pattern_df: pd.DataFrame,
    hits: list[tuple[str, float]],
    out_path: Path,
    cfg: FormaConfig,
) -> None:
    try:
        import matplotlib.dates as mdates
        import matplotlib.pyplot as plt
    except ImportError:
        logging.warning("matplotlib 없음 — 차트 생략")
        return

    if not hits:
        logging.warning("추천 종목 없음 — 차트 생략")
        return

    compare_start = cfg.compare_from or cfg.pattern_from
    compare_end = cfg.compare_to or cfg.pattern_to
    ncol = max(1, cfg.chart_grid_cols)
    n_rec = len(hits)
    n_row_rec = max(1, math.ceil(n_rec / ncol))
    n_rows = 1 + n_row_rec
    fig_w = cfg.chart_panel_w * ncol
    fig_h = cfg.chart_panel_h * (cfg.chart_target_row_scale + n_row_rec)
    fig = plt.figure(figsize=(fig_w, fig_h), layout="constrained")
    height_ratios = [cfg.chart_target_row_scale] + [1.0] * n_row_rec
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
            cdf = clean_data(
                get_stock_data(ticker, compare_start, compare_end),
            )
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
    fig.savefig(
        out_path,
        dpi=cfg.chart_dpi,
        bbox_inches="tight",
        pad_inches=0.25,
    )
    plt.close(fig)
    print(f"차트 저장: {out_path}")
