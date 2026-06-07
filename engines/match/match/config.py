"""Match 설정."""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

_ROOT = Path(__file__).resolve().parent.parent
_PKG = Path(__file__).resolve().parent
_SNAPATCH_ROOT = _ROOT.parent.parent
MATCH_DIR = _ROOT


def resolve_ticker_csv(path: Path | str) -> Path:
    """후보 종목 CSV — engines/match/ 아래 파일만 허용."""
    raw = Path(path)
    resolved = (MATCH_DIR / raw.name if not raw.is_absolute() else raw).resolve()
    try:
        resolved.relative_to(MATCH_DIR.resolve())
    except ValueError as exc:
        raise ValueError(
            f"ticker CSV는 engines/match/ 아래만 사용할 수 있습니다: {resolved}",
        ) from exc
    if not resolved.is_file():
        raise FileNotFoundError(f"ticker CSV 없음: {resolved}")
    return resolved


@dataclass
class FormaConfig:
    pattern_ticker: str = "397030"
    pattern_from: str = "20251103"
    pattern_to: str = "20260514"
    compare_from: str | None = None
    compare_to: str | None = None

    top_n: int = 20
    max_workers: int = 4
    use_threads_only: bool = field(
        default_factory=lambda: sys.platform == "win32",
    )
    ticker_csv: Path = field(default_factory=lambda: MATCH_DIR / "uni.csv")
    exclude_pattern_ticker: bool = True

    stage1_top_k: int = 60
    stage1_rank_by: Literal["combined", "sax", "feat"] = "combined"
    stage1_preview: int = 10

    heartbeat_sec: float = 30.0
    skip_rule_filter: bool = False
    rule_std_ratio: tuple[float, float] = (0.2, 5.0)
    rule_range_ratio: tuple[float, float] = (0.15, 6.0)
    sax_segments: int = 12
    sax_alphabet: int = 5
    combined_sax_weight: float = 0.5
    combined_feat_weight: float = 0.5

    save_similarity_chart: bool = True
    chart_output_path: Path | None = None
    chart_grid_cols: int = 3
    chart_panel_w: float = 5.2
    chart_panel_h: float = 3.6
    chart_target_row_scale: float = 1.45
    chart_dpi: int = 140

    request_timeout_sec: float = 30.0

    def __post_init__(self) -> None:
        if self.compare_from is None:
            self.compare_from = self.pattern_from
        if self.compare_to is None:
            self.compare_to = self.pattern_to
        self.ticker_csv = resolve_ticker_csv(self.ticker_csv)
        if self.chart_output_path is not None:
            self.chart_output_path = Path(self.chart_output_path)

    @property
    def pattern_id(self) -> str:
        return str(self.pattern_ticker).strip().strip("'").zfill(6)

    def default_chart_path(self) -> Path:
        if self.chart_output_path:
            return self.chart_output_path
        out_dir = _SNAPATCH_ROOT / "outputs" / "match"
        out_dir.mkdir(parents=True, exist_ok=True)
        return (
            out_dir
            / f"match_{self.pattern_id}_"
            f"{self.pattern_from}_{self.pattern_to}.png"
        )
