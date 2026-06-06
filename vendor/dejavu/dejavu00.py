"""
dejavu00 — 과거 유사 구간 탐색 + 이후 수익률 분석 (검토 반영 개선판).

2.main.py 대비 주요 변경:
- METHOD_META: 방법별 스코어 방향·열 이름 통일 (DTW는 거리+유사도 변환)
- 상수 구간: pearson/spearman 사전 차단 (SciPy nan/경고 흡수)
- 벡터 스캔: pearson/cosine/euclidean/manhattan 일괄 계산 (DTW·spearman은 선택)
- DTW: distance_fast + pruning + window (YAML)
- strict_backtest_mode: 타겟일 이후 데이터 절단 (룩어헤드 완화)
- dense_rescan: coarse 스캔 후 상위 후보 주변 정밀 재탐색
- regime_filter: 변동성·추세 부호·MDD 로 후보 제한 (종가 기준)
- ensemble.robust: 방법별 TOP pool 교집합 + median 집계
- STUMPY Matrix Profile: 스크립트 내장 HistoricalAnalogEngine
- 차트: index100(시작=100) / minmax 선택
- 보고서: 정규화 vs 원가 수익률 해석 안내, 미래수익률 정의(종가→종가)

실행: python dejavu00.py [similarity_run.yml]
"""

from __future__ import annotations

import io
import logging
import sys
from contextlib import redirect_stdout
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

try:
    import yaml
except ModuleNotFoundError as exc:
    sys.stderr.write(
        "오류: PyYAML 이 설치되어 있지 않습니다.\n"
        "  pip install PyYAML\n"
    )
    raise SystemExit(1) from exc

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from pykrx import stock
from scipy.spatial.distance import cosine, euclidean, cityblock
from scipy.stats import pearsonr, spearmanr

try:
    from dtaidistance import dtw as dtw_mod

    _HAS_DTW = True
except ImportError:
    dtw_mod = None  # type: ignore[misc, assignment]
    _HAS_DTW = False

logging.getLogger("dtaidistance").setLevel(logging.CRITICAL)

# --- STUMPY Matrix Profile (과거 유사 구간, 내장) ---
try:
    import stumpy

    _HAS_STUMPY = True
except ImportError:
    stumpy = None  # type: ignore[misc, assignment]
    _HAS_STUMPY = False


@dataclass
class HistoricalAnalog:
    rank: int
    start_date: pd.Timestamp
    end_date: pd.Timestamp
    distance: float
    similarity_pct: float
    forward_returns: dict[int, float]


@dataclass
class AnalogResult:
    analogs: list[HistoricalAnalog]
    forward_days: list[int]
    query_start: pd.Timestamp
    query_end: pd.Timestamp
    ticker: str = ""


class HistoricalAnalogEngine:
    def __init__(
        self,
        forward_days: list[int] | None = None,
        top_k: int = 5,
        exclusion_zone_multiplier: float = 2.0,
    ) -> None:
        if not _HAS_STUMPY:
            raise ImportError("stumpy 가 설치되어 있지 않습니다. pip install stumpy")
        self.forward_days = forward_days or [5, 10, 20, 40, 60]
        self.top_k = max(1, int(top_k))
        self.exclusion_zone_multiplier = float(exclusion_zone_multiplier)

    def run(
        self,
        df: pd.DataFrame,
        query_start: str,
        query_end: str,
    ) -> AnalogResult:
        if "close" not in df.columns:
            raise ValueError("df 에 'close' 열이 필요합니다.")
        close = df["close"].astype(float)
        idx = pd.DatetimeIndex(pd.to_datetime(df.index))
        q0 = pd.Timestamp(query_start)
        q1 = pd.Timestamp(query_end)
        if q0 not in idx or q1 not in idx:
            raise ValueError(f"쿼리 날짜가 인덱스에 없습니다: {query_start} ~ {query_end}")
        i0 = int(idx.get_loc(q0))
        i1 = int(idx.get_loc(q1))
        if i1 < i0:
            raise ValueError("query_end 가 query_start 보다 앞설 수 없습니다.")
        m = i1 - i0 + 1
        if m < 3:
            raise ValueError("쿼리 창 길이가 너무 짧습니다.")
        if i0 < m:
            raise ValueError("쿼리 이전 데이터가 부족합니다.")

        series = close.values.astype(np.float64)
        query = series[i0 : i1 + 1]
        mult = float(self.exclusion_zone_multiplier)
        cushion = max(0, int(round((mult - 1.0) * m)))

        max_start = i0 - m
        if max_start < 0:
            raise ValueError("유사 구간을 둘 만큼 과거 데이터가 없습니다.")

        search = series[:i0]
        try:
            match_out = stumpy.match(
                query,
                search,
                max_matches=min(max(500, len(search)), self.top_k * 64),
            )
        except TypeError:
            match_out = stumpy.match(query, search)

        if isinstance(match_out, tuple):
            distances = np.asarray(match_out[0], dtype=float).reshape(-1)
            locs = np.asarray(match_out[1], dtype=int).reshape(-1)
        else:
            distances = np.asarray(match_out[:, 0], dtype=float)
            locs = np.asarray(match_out[:, 1], dtype=int)

        ticker = str(df.attrs.get("ticker", ""))
        analogs: list[HistoricalAnalog] = []
        rank = 0
        for dist, loc in zip(distances, locs, strict=False):
            start_i = int(loc)
            end_i = start_i + m - 1
            if end_i >= i0:
                continue
            if start_i > i0 - m - cushion:
                continue
            if any(a.start_date == idx[start_i] for a in analogs):
                continue
            rank += 1
            sim_pct = 100.0 / (1.0 + float(dist)) if np.isfinite(dist) else float("nan")
            fwd = self._forward_returns(series, end_i)
            analogs.append(
                HistoricalAnalog(
                    rank=rank,
                    start_date=idx[start_i],
                    end_date=idx[end_i],
                    distance=float(dist),
                    similarity_pct=float(sim_pct),
                    forward_returns=fwd,
                )
            )
            if len(analogs) >= self.top_k:
                break

        if not analogs:
            raise ValueError("조건을 만족하는 유사 구간을 찾지 못했습니다.")

        return AnalogResult(
            analogs=analogs,
            forward_days=list(self.forward_days),
            query_start=q0,
            query_end=q1,
            ticker=ticker,
        )

    def _forward_returns(self, series: np.ndarray, end_i: int) -> dict[int, float]:
        out: dict[int, float] = {}
        base = float(series[end_i])
        for d in self.forward_days:
            j = end_i + int(d)
            if j >= len(series) or base == 0.0:
                out[int(d)] = float("nan")
            else:
                out[int(d)] = float(series[j] / base - 1.0)
        return out

    def print_report(self, result: AnalogResult) -> None:
        print(f"=== Matrix Profile (STUMPY) — {result.ticker or 'N/A'} ===")
        print(
            f"쿼리: {result.query_start.date()} ~ {result.query_end.date()} "
            f"| forward_days={result.forward_days}"
        )
        for a in result.analogs:
            fwd_s = ", ".join(
                f"{d}d:{a.forward_returns.get(d, float('nan')) * 100:.2f}%"
                for d in result.forward_days
            )
            print(
                f"  #{a.rank} {a.start_date.date()}~{a.end_date.date()} "
                f"dist={a.distance:.4f} sim%={a.similarity_pct:.2f} | {fwd_s}"
            )


log = logging.getLogger("dejavu00")

STUMPY_ALIASES = frozenset({"stumpy", "matrix_profile"})

METHOD_META: dict[str, dict[str, Any]] = {
    "pearson": {
        "higher_is_better": True,
        "label": "Pearson",
        "score_col": "유사도",
        "vectorized": True,
    },
    "cosine": {
        "higher_is_better": True,
        "label": "Cosine",
        "score_col": "유사도",
        "vectorized": True,
    },
    "euclidean": {
        "higher_is_better": True,
        "label": "Euclidean",
        "score_col": "유사도",
        "vectorized": True,
    },
    "manhattan": {
        "higher_is_better": True,
        "label": "Manhattan",
        "score_col": "유사도",
        "vectorized": True,
    },
    "spearman": {
        "higher_is_better": True,
        "label": "Spearman",
        "score_col": "유사도",
        "vectorized": False,
    },
    "dtw": {
        "higher_is_better": False,
        "label": "DTW",
        "score_col": "DTW거리",
        "similarity_col": "DTW유사도",
        "vectorized": False,
    },
    "stumpy": {
        "higher_is_better": True,
        "label": "STUMPY",
        "score_col": "유사도",
        "vectorized": False,
    },
    "ensemble": {
        "higher_is_better": True,
        "label": "Ensemble",
        "score_col": "ensemble점수",
        "vectorized": False,
    },
}

INTERPRETATION_HEADER = (
    "【해석 안내】 유사도는 정규화된 가격 패턴(기본: z-score) 기준이며, "
    "유사구간수익률·미래수익률은 원 종가 기준(%)입니다. "
    "패턴 형태가 비슷해도 수익률 부호·크기는 다를 수 있습니다. "
    "미래수익률은 관찰 종료일 종가 대비 N거래일 후 종가(종가→종가)입니다."
)


@dataclass(frozen=True)
class SimilarityRecord:
    rank: int
    start_i: int
    start_date: str
    end_date: str
    raw_score: float
    similarity: float
    window_return_pct: float
    forward_return_pct: float
    method: str
    score_label: str = "유사도"

    def to_row(self) -> dict[str, Any]:
        row: dict[str, Any] = {
            "순위": self.rank,
            "시작일": self.start_date,
            "종료일": self.end_date,
            self.score_label: self.raw_score
            if self.method == "dtw"
            else self.similarity,
            "유사구간수익률": self.window_return_pct,
            "미래수익률": self.forward_return_pct,
        }
        if self.method == "dtw":
            row["DTW거리"] = self.raw_score
            row["DTW유사도"] = self.similarity
        return row


@dataclass
class AnalysisContext:
    ticker: str
    close: pd.Series
    values: np.ndarray
    ws: "WindowSpec"
    target_norm: np.ndarray
    target_ts: pd.Timestamp
    forward_days: int
    obs: int
    out_dir: Path
    date_tag: str
    methods: list[str]
    matrix_profile_cfg: dict[str, Any]
    scan_step: int
    scan_description: str
    use_dtw: bool
    dtw_window_ratio: float
    chart_mode: Literal["index100", "minmax"]
    match_basis: Literal["price", "return"]
    strict_backtest: bool
    dense_rescan: bool
    dense_radius: int
    dense_top_m: int
    top_n_similar: int = 5
    chart_prefix: str = "pattern_comparison"
    save_csv: bool = True
    save_txt: bool = True
    save_md: bool = True
    price_values: np.ndarray = field(default_factory=lambda: np.array([]))
    ensemble_enabled: bool = False
    ensemble_weights: dict[str, float] = field(default_factory=dict)
    distribution_enabled: bool = False
    bootstrap_samples: int = 500
    target_window_return_pct: float = float("nan")
    return_alignment_enabled: bool = False
    return_alignment_weight: float = 0.25
    regime_filter_enabled: bool = False
    regime_vol_max_relative_diff: float = 0.3
    regime_trend_require_same_sign: bool = True
    regime_mdd_max_diff_pp: float = 5.0
    ensemble_robust_enabled: bool = True
    ensemble_robust_top_pool: int = 50
    ensemble_robust_min_methods: int = 2
    ensemble_robust_aggregate: str = "median"


@dataclass(frozen=True)
class RegimeFeatures:
    """관찰 구간 regime 지표 (종가 기준)."""

    realized_vol: float
    window_return_pct: float
    max_drawdown_pct: float


@dataclass(frozen=True)
class WindowSpec:
    target_end_idx: int
    obs: int
    target_start_idx: int

    @property
    def target_slice(self) -> slice:
        return slice(self.target_start_idx, self.target_end_idx + 1)


def _project_root() -> Path:
    return Path(__file__).resolve().parent


def configure_stdio_utf8() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError, AttributeError):
                pass


def setup_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(levelname)s %(message)s",
    )


def _format_float_cell(x: Any) -> str:
    if x is None or (
        isinstance(x, (float, np.floating)) and (np.isnan(x) or np.isinf(x))
    ):
        return ""
    return f"{float(x):.4f}"


def format_dataframe_table(df: pd.DataFrame) -> str:
    disp = df.copy()
    for col in disp.columns:
        if pd.api.types.is_float_dtype(disp[col]):
            disp[col] = disp[col].map(_format_float_cell)
    return disp.to_string(index=False)


def dataframe_to_markdown(df: pd.DataFrame) -> str:
    disp = df.copy()
    for col in disp.columns:
        if pd.api.types.is_float_dtype(disp[col]):
            disp[col] = disp[col].map(_format_float_cell)
    header = "| " + " | ".join(str(c) for c in disp.columns) + " |"
    sep = "| " + " | ".join(["---"] * len(disp.columns)) + " |"
    body = [
        "| " + " | ".join(str(v) for v in row) + " |" for _, row in disp.iterrows()
    ]
    return "\n".join([header, sep, *body])


def load_config(path: Path | None = None) -> dict[str, Any]:
    root = _project_root()
    if path is not None:
        cfg_path = path
    else:
        cfg_path = root / "similarity_run.yml"
        if not cfg_path.is_file():
            alt = root / "similarity_run.yaml"
            if alt.is_file():
                cfg_path = alt
    if not cfg_path.is_file():
        raise FileNotFoundError(f"설정 파일이 없습니다: {cfg_path}")
    with cfg_path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError("YAML 루트는 객체(매핑)이어야 합니다.")
    return data


def _is_constant(arr: np.ndarray) -> bool:
    flat = arr.reshape(-1)
    if flat.size == 0:
        return True
    return bool(np.allclose(flat, flat[0], equal_nan=True))


def safe_zscore(values: np.ndarray) -> np.ndarray:
    std = float(np.std(values))
    if std == 0.0:
        return np.zeros_like(values, dtype=float)
    return (values - float(np.mean(values))) / std


def zscore_rows(windows: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(n_win, obs) → z-score 행렬, 행별 std."""
    mean = windows.mean(axis=1, keepdims=True)
    std = windows.std(axis=1, keepdims=True)
    std_safe = np.where(std < 1e-12, 1.0, std)
    z = (windows - mean) / std_safe
    row_std = std.reshape(-1)
    return z, row_std.reshape(-1)


def safe_minmax(values: np.ndarray) -> np.ndarray:
    lo, hi = float(np.min(values)), float(np.max(values))
    if hi == lo:
        return np.zeros_like(values, dtype=float)
    return (values - lo) / (hi - lo)


def normalize_chart_series(seg: np.ndarray, mode: str) -> np.ndarray:
    if mode == "index100":
        base = float(seg[0])
        if base == 0:
            return np.zeros_like(seg, dtype=float)
        return (seg / base) * 100.0
    return safe_minmax(seg)


def resolve_trading_date(index: pd.DatetimeIndex, label: str | None) -> pd.Timestamp:
    if not label or str(label).lower() == "today":
        raw = pd.Timestamp(datetime.now().date())
    else:
        raw = pd.Timestamp(str(label))
    ts = raw.normalize()
    valid = index[index <= ts]
    if valid.empty:
        raise ValueError(f"타겟 날짜를 인덱스 안으로 맞출 수 없습니다: {label}")
    return pd.Timestamp(valid[-1])


def fetch_close(cfg: dict[str, Any]) -> pd.Series:
    start = str(cfg["data_start"]).replace("-", "")
    end = datetime.now().strftime("%Y%m%d")
    ticker = cfg["ticker"]
    col = cfg.get("price_column", "종가")
    df = stock.get_market_ohlcv_by_date(start, end, ticker)
    if df.empty:
        raise ValueError(f"시세 데이터 없음: {ticker} ({start}~{end})")
    if col not in df.columns:
        raise KeyError(f"컬럼 없음: {col} / 사용 가능: {list(df.columns)}")
    s = df[col].astype(float).copy()
    s.index = pd.to_datetime(s.index)
    if not isinstance(s.index, pd.DatetimeIndex):
        s.index = pd.DatetimeIndex(s.index)
    s = s.sort_index()
    s = s[~s.index.duplicated(keep="last")]
    return s


def build_match_series(close: pd.Series, basis: str) -> np.ndarray:
    if basis == "return":
        ret = close.pct_change().fillna(0.0).values.astype(float)
        return ret
    return close.values.astype(float)


def window_spec(close: pd.Series, target_ts: pd.Timestamp, obs: int) -> WindowSpec:
    if obs < 3:
        raise ValueError("observation_days 는 3 이상이어야 합니다.")
    if target_ts not in close.index:
        raise KeyError(f"타겟일이 데이터에 없습니다: {target_ts}")
    end_idx = int(close.index.get_loc(target_ts))
    start_idx = end_idx - obs + 1
    if start_idx < 0:
        raise ValueError(
            f"데이터 부족: 종가 {len(close)}일, 관찰 {obs}일 필요."
        )
    return WindowSpec(
        target_end_idx=end_idx,
        obs=obs,
        target_start_idx=start_idx,
    )


def pattern_return_pct(close: np.ndarray | pd.Series) -> float:
    a = float(close.iloc[0]) if hasattr(close, "iloc") else float(close[0])
    b = float(close.iloc[-1]) if hasattr(close, "iloc") else float(close[-1])
    if a == 0:
        return float("nan")
    return (b / a - 1.0) * 100.0


def compute_regime_features(close_slice: np.ndarray | pd.Series) -> RegimeFeatures:
    """변동성(일수익률 std), 관찰 누적수익률(%), 구간 최대낙폭(%)."""
    arr = (
        close_slice.astype(float).values.reshape(-1)
        if hasattr(close_slice, "values")
        else np.asarray(close_slice, dtype=float).reshape(-1)
    )
    if arr.size < 2:
        return RegimeFeatures(
            realized_vol=float("nan"),
            window_return_pct=float("nan"),
            max_drawdown_pct=float("nan"),
        )
    rets = np.diff(arr) / arr[:-1]
    vol = float(np.std(rets, ddof=1)) if rets.size >= 2 else float("nan")
    win_ret = pattern_return_pct(arr)
    peak = np.maximum.accumulate(arr)
    dd = (arr - peak) / np.where(peak != 0, peak, np.nan)
    mdd_pct = float(-np.nanmin(dd) * 100.0) if dd.size else float("nan")
    return RegimeFeatures(
        realized_vol=vol,
        window_return_pct=win_ret,
        max_drawdown_pct=mdd_pct,
    )


def passes_regime_filter(
    target: RegimeFeatures,
    candidate: RegimeFeatures,
    vol_max_relative_diff: float,
    trend_require_same_sign: bool,
    mdd_max_diff_pp: float,
) -> bool:
    if np.isfinite(target.realized_vol) and np.isfinite(candidate.realized_vol):
        denom = max(abs(target.realized_vol), 1e-12)
        if abs(candidate.realized_vol - target.realized_vol) / denom > vol_max_relative_diff:
            return False
    if trend_require_same_sign:
        if np.isfinite(target.window_return_pct) and np.isfinite(
            candidate.window_return_pct
        ):
            if target.window_return_pct * candidate.window_return_pct < 0:
                return False
    if np.isfinite(target.max_drawdown_pct) and np.isfinite(candidate.max_drawdown_pct):
        if abs(candidate.max_drawdown_pct - target.max_drawdown_pct) > mdd_max_diff_pp:
            return False
    return True


def filter_indices_by_regime(
    close: pd.Series,
    indices: list[int],
    obs: int,
    target_features: RegimeFeatures,
    vol_max_relative_diff: float,
    trend_require_same_sign: bool,
    mdd_max_diff_pp: float,
) -> tuple[list[int], int]:
    """regime 통과한 시작 인덱스만 반환. (filtered, rejected_count)."""
    kept: list[int] = []
    rejected = 0
    for i in indices:
        seg = close.iloc[i : i + obs]
        feat = compute_regime_features(seg)
        if passes_regime_filter(
            target_features,
            feat,
            vol_max_relative_diff,
            trend_require_same_sign,
            mdd_max_diff_pp,
        ):
            kept.append(i)
        else:
            rejected += 1
    return kept, rejected


def forward_return_pct(values: np.ndarray, end_idx: int, horizon: int) -> float:
    """관찰 창 마지막 종가 → horizon 거래일 후 종가 (%)."""
    j = end_idx + horizon
    if j >= len(values) or end_idx < 0:
        return float("nan")
    a = float(values[end_idx])
    b = float(values[j])
    if a == 0:
        return float("nan")
    return (b / a - 1.0) * 100.0


def distance_to_similarity(dist: float) -> float:
    if not np.isfinite(dist):
        return float("nan")
    return 1.0 / (1.0 + float(dist))


def similarity_scores_pair(a: np.ndarray, b: np.ndarray) -> dict[str, float]:
    flat_a = a.reshape(-1)
    flat_b = b.reshape(-1)
    out: dict[str, float] = {}

    c_sim = 1.0 - float(cosine(flat_a, flat_b))
    out["cosine"] = c_sim if np.isfinite(c_sim) else float("nan")

    euc = float(euclidean(flat_a, flat_b))
    out["euclidean"] = distance_to_similarity(euc)

    man = float(cityblock(flat_a, flat_b))
    out["manhattan"] = distance_to_similarity(man)

    if _is_constant(flat_a) or _is_constant(flat_b):
        out["pearson"] = float("nan")
        out["spearman"] = float("nan")
    else:
        pr, _ = pearsonr(flat_a, flat_b)
        sp, _ = spearmanr(flat_a, flat_b)
        out["pearson"] = float(pr) if np.isfinite(pr) else float("nan")
        out["spearman"] = float(sp) if np.isfinite(sp) else float("nan")
    return out


def dtw_distance(
    a: np.ndarray,
    b: np.ndarray,
    window_ratio: float = 0.1,
) -> float:
    """C 확장 미설치 환경에서는 pure Python distance()만 사용 (스팸 로그 방지)."""
    if not _HAS_DTW or dtw_mod is None:
        return float("nan")
    x = np.asarray(a, dtype=np.double).reshape(-1)
    y = np.asarray(b, dtype=np.double).reshape(-1)
    try:
        return float(dtw_mod.distance(x, y))
    except Exception:
        return float("nan")


def max_hist_start(close_len: int, obs: int, target_start_idx: int) -> int:
    cap_by_data = close_len - obs
    cap_by_target = target_start_idx - obs
    return max(0, min(cap_by_data, cap_by_target))


def _candidate_indices(i_max: int, step: int) -> list[int]:
    step = max(1, int(step))
    return list(range(0, i_max + 1, step))


def vectorized_scan(
    values: np.ndarray,
    target_norm: np.ndarray,
    obs: int,
    i_max: int,
    indices: list[int],
    methods_needed: set[str],
) -> dict[int, dict[str, Any]]:
    """indices에 해당하는 시작 i만 계산."""
    if not indices:
        return {}
    target_const = _is_constant(target_norm)
    out: dict[int, dict[str, Any]] = {}

    vec_methods = methods_needed & {"pearson", "cosine", "euclidean", "manhattan"}
    need_matrix = bool(vec_methods)

    if need_matrix:
        windows = np.stack(
            [values[i : i + obs] for i in indices], axis=0
        )
        w_z, row_std = zscore_rows(windows)
        constant_rows = (row_std < 1e-12) | target_const
        t = target_norm.reshape(1, -1)
        dots = (w_z * t).sum(axis=1) / obs

        if "pearson" in vec_methods or "cosine" in vec_methods:
            denom = np.linalg.norm(w_z, axis=1) * np.linalg.norm(target_norm)
            denom = np.where(denom < 1e-12, np.nan, denom)
            cos_vals = (w_z @ target_norm) / denom
            cos_vals = np.where(constant_rows, np.nan, cos_vals)

        if "euclidean" in vec_methods:
            euc = np.linalg.norm(w_z - target_norm, axis=1)
            euc_sim = np.array([distance_to_similarity(d) for d in euc])
            euc_sim = np.where(constant_rows, np.nan, euc_sim)

        if "manhattan" in vec_methods:
            man = np.sum(np.abs(w_z - target_norm), axis=1)
            man_sim = np.array([distance_to_similarity(d) for d in man])
            man_sim = np.where(constant_rows, np.nan, man_sim)

    for k, i in enumerate(indices):
        scores: dict[str, float] = {}
        if need_matrix:
            if "pearson" in vec_methods:
                scores["pearson"] = float(dots[k]) if not constant_rows[k] else float("nan")
            if "cosine" in vec_methods:
                scores["cosine"] = float(cos_vals[k]) if not constant_rows[k] else float("nan")
            if "euclidean" in vec_methods:
                scores["euclidean"] = float(euc_sim[k])
            if "manhattan" in vec_methods:
                scores["manhattan"] = float(man_sim[k])

        if "spearman" in methods_needed:
            hist_norm = safe_zscore(values[i : i + obs])
            if target_const or _is_constant(hist_norm):
                scores["spearman"] = float("nan")
            else:
                sp, _ = spearmanr(target_norm, hist_norm)
                scores["spearman"] = float(sp) if np.isfinite(sp) else float("nan")

        row: dict[str, Any] = {"i": i, "scores": scores}
        out[i] = row
    return out


def enrich_dtw_rows(
    rows_by_i: dict[int, dict[str, Any]],
    values: np.ndarray,
    target_norm: np.ndarray,
    obs: int,
    indices: list[int],
    window_ratio: float,
) -> None:
    for i in indices:
        hist_norm = safe_zscore(values[i : i + obs])
        dist = dtw_distance(target_norm, hist_norm, window_ratio)
        if i not in rows_by_i:
            rows_by_i[i] = {"i": i, "scores": {}}
        rows_by_i[i]["dtw_dist"] = dist
        rows_by_i[i]["dtw_sim"] = distance_to_similarity(dist)


def scan_with_optional_dense(
    close: pd.Series,
    values: np.ndarray,
    target_norm: np.ndarray,
    obs: int,
    target_start_idx: int,
    methods: list[str],
    use_dtw: bool,
    step: int,
    dense_rescan: bool,
    dense_radius: int,
    dense_top_m: int,
    dtw_window_ratio: float,
    regime_enabled: bool = False,
    target_regime: RegimeFeatures | None = None,
    regime_vol_max_relative_diff: float = 0.3,
    regime_trend_require_same_sign: bool = True,
    regime_mdd_max_diff_pp: float = 5.0,
) -> dict[int, dict[str, Any]]:
    i_max = max_hist_start(len(values), obs, target_start_idx)
    if i_max < 0:
        raise ValueError(
            "유사 구간 스캔 상한이 음수입니다. observation_days 또는 데이터 기간을 확인하세요."
        )

    coarse_is = _candidate_indices(i_max, step)
    if regime_enabled and target_regime is not None:
        coarse_is, n_rej = filter_indices_by_regime(
            close,
            coarse_is,
            obs,
            target_regime,
            regime_vol_max_relative_diff,
            regime_trend_require_same_sign,
            regime_mdd_max_diff_pp,
        )
        if n_rej:
            log.info("regime filter: coarse 후보 %d개 제외", n_rej)

    method_set = {m.lower() for m in methods if m not in STUMPY_ALIASES}
    if use_dtw:
        method_set.add("dtw")

    rows_by_i = vectorized_scan(
        values, target_norm, obs, i_max, coarse_is, method_set
    )
    if use_dtw:
        enrich_dtw_rows(
            rows_by_i, values, target_norm, obs, coarse_is, dtw_window_ratio
        )

    if dense_rescan and dense_top_m > 0 and dense_radius > 0:
        ref_method = next(
            (m for m in ("pearson", "cosine", "euclidean") if m in method_set),
            None,
        )
        if ref_method:
            ranked = rank_indices(list(rows_by_i.values()), ref_method, dense_top_m)
            extra: set[int] = set()
            for i0 in ranked:
                lo = max(0, i0 - dense_radius)
                hi = min(i_max, i0 + dense_radius)
                for i in range(lo, hi + 1):
                    if i not in rows_by_i:
                        extra.add(i)
            if extra:
                extra_list = sorted(extra)
                if regime_enabled and target_regime is not None:
                    extra_list, n_rej = filter_indices_by_regime(
                        close,
                        extra_list,
                        obs,
                        target_regime,
                        regime_vol_max_relative_diff,
                        regime_trend_require_same_sign,
                        regime_mdd_max_diff_pp,
                    )
                    if n_rej:
                        log.info("regime filter: dense 추가 후보 %d개 제외", n_rej)
                added = vectorized_scan(
                    values, target_norm, obs, i_max, extra_list, method_set
                )
                rows_by_i.update(added)
                if use_dtw:
                    enrich_dtw_rows(
                        rows_by_i,
                        values,
                        target_norm,
                        obs,
                        extra_list,
                        dtw_window_ratio,
                    )
                log.info(
                    "dense rescan: %d 추가 후보 (±%d거래일, 상위 %d 기준)",
                    len(extra_list),
                    dense_radius,
                    dense_top_m,
                )

    return rows_by_i


def rank_indices(
    rows: list[dict[str, Any]],
    method: str,
    top_n: int,
) -> list[int]:
    method_l = method.lower()
    meta = METHOD_META.get(method_l, {"higher_is_better": True})
    higher = bool(meta.get("higher_is_better", True))

    if method_l == "dtw":
        valid = [
            (r["i"], r.get("dtw_dist", float("nan")))
            for r in rows
            if np.isfinite(r.get("dtw_dist", np.nan))
        ]
        valid.sort(key=lambda x: x[1])
        return [i for i, _ in valid[:top_n]]

    scores_list = [
        (r["i"], r["scores"].get(method_l, float("nan"))) for r in rows
    ]
    scores_list = [(i, s) for i, s in scores_list if np.isfinite(s)]
    scores_list.sort(key=lambda x: x[1], reverse=higher)
    return [i for i, _ in scores_list[:top_n]]


def return_alignment_score(target_ret_pct: float, window_ret_pct: float) -> float:
    """관찰 구간 누적 수익률이 타겟에 가까울수록 1에 근접."""
    if not np.isfinite(target_ret_pct) or not np.isfinite(window_ret_pct):
        return float("nan")
    diff = abs(float(target_ret_pct) - float(window_ret_pct))
    return 1.0 / (1.0 + diff / 10.0)


def rank_indices_with_return_alignment(
    rows: list[dict[str, Any]],
    method: str,
    top_n: int,
    close: pd.Series,
    obs: int,
    target_ret_pct: float,
    weight: float,
) -> list[int]:
    """패턴 스코어와 관찰 수익률 근접도를 가중 합산해 순위."""
    w = float(np.clip(weight, 0.0, 1.0))
    method_l = method.lower()
    pattern_raw: dict[int, float] = {}
    return_raw: dict[int, float] = {}

    for r in rows:
        i = int(r["i"])
        sim_slice = close.iloc[i : i + obs]
        return_raw[i] = return_alignment_score(
            target_ret_pct, pattern_return_pct(sim_slice)
        )
        if method_l == "dtw":
            d = r.get("dtw_dist", float("nan"))
            pattern_raw[i] = (
                distance_to_similarity(float(d)) if np.isfinite(d) else float("nan")
            )
        else:
            pattern_raw[i] = float(r["scores"].get(method_l, float("nan")))

    norm_p = minmax_normalize(pattern_raw)
    norm_r = minmax_normalize(return_raw)
    combined: dict[int, float] = {}
    for i in set(norm_p) | set(norm_r):
        p = norm_p.get(i, float("nan"))
        r = norm_r.get(i, float("nan"))
        if np.isfinite(p) and np.isfinite(r):
            combined[i] = (1.0 - w) * p + w * r
        elif np.isfinite(p):
            combined[i] = p
        elif np.isfinite(r):
            combined[i] = r

    ranked = sorted(combined.items(), key=lambda x: x[1], reverse=True)
    return [i for i, _ in ranked[:top_n]]


def raw_score_from_row(row: dict[str, Any], method: str) -> float:
    method_l = method.lower()
    if method_l == "dtw":
        v = row.get("dtw_sim", float("nan"))
        return float(v) if np.isfinite(v) else float("nan")
    return float(row["scores"].get(method_l, float("nan")))


def minmax_normalize(scores: dict[int, float]) -> dict[int, float]:
    valid = {i: s for i, s in scores.items() if np.isfinite(s)}
    if not valid:
        return {}
    lo, hi = min(valid.values()), max(valid.values())
    if hi <= lo:
        return {i: 1.0 for i in valid}
    return {i: (s - lo) / (hi - lo) for i, s in valid.items()}


def compute_ensemble_scores(
    rows_by_i: dict[int, dict[str, Any]],
    weights: dict[str, float],
) -> dict[int, float]:
    norm_parts: dict[str, dict[int, float]] = {}
    for method, w in weights.items():
        if w <= 0:
            continue
        raw = {i: raw_score_from_row(r, method) for i, r in rows_by_i.items()}
        norm_parts[method] = minmax_normalize(raw)

    combined: dict[int, float] = {}
    for i in rows_by_i:
        s = 0.0
        w_sum = 0.0
        for method, w in weights.items():
            if w <= 0:
                continue
            v = norm_parts.get(method, {}).get(i, float("nan"))
            if np.isfinite(v):
                s += w * v
                w_sum += w
        if w_sum > 0:
            combined[i] = s / w_sum
    return combined


def ensemble_voting_methods(
    methods: list[str],
    weights: dict[str, float],
) -> list[str]:
    return [
        m
        for m in methods
        if m != "stumpy" and weights.get(m, 0) > 0 and (m in METHOD_META or m == "dtw")
    ]


def robust_ensemble_candidate_pool(
    rows_by_i: dict[int, dict[str, Any]],
    voting_methods: list[str],
    top_pool: int,
    min_methods: int,
) -> set[int]:
    """상위 top_pool 안에 min_methods개 이상 방법이 넣은 시작 인덱스만."""
    if not voting_methods or min_methods < 1:
        return set(rows_by_i.keys())
    rows_list = list(rows_by_i.values())
    votes: dict[int, int] = {i: 0 for i in rows_by_i}
    for method in voting_methods:
        for i in rank_indices(rows_list, method, top_pool):
            votes[i] = votes.get(i, 0) + 1
    return {i for i, c in votes.items() if c >= min_methods}


def compute_ensemble_scores_median(
    rows_by_i: dict[int, dict[str, Any]],
    weights: dict[str, float],
    candidate_is: set[int] | None = None,
) -> dict[int, float]:
    """방법별 정규화 점수의 가중 중앙값(robust aggregate)."""
    methods = [m for m, w in weights.items() if w > 0 and (m in METHOD_META or m == "dtw")]
    norm_parts: dict[str, dict[int, float]] = {}
    for method in methods:
        raw = {
            i: raw_score_from_row(r, method)
            for i, r in rows_by_i.items()
            if candidate_is is None or i in candidate_is
        }
        norm_parts[method] = minmax_normalize(raw)

    combined: dict[int, float] = {}
    pool = candidate_is if candidate_is is not None else set(rows_by_i.keys())
    for i in pool:
        if i not in rows_by_i:
            continue
        vals: list[float] = []
        for method in methods:
            v = norm_parts.get(method, {}).get(i, float("nan"))
            if np.isfinite(v):
                vals.append(float(v))
        if vals:
            combined[i] = float(np.median(vals))
    return combined


def rank_indices_ensemble(
    rows_by_i: dict[int, dict[str, Any]],
    weights: dict[str, float],
    top_n: int,
    methods: list[str] | None = None,
    robust_enabled: bool = True,
    robust_top_pool: int = 50,
    robust_min_methods: int = 2,
    robust_aggregate: str = "median",
) -> tuple[list[int], dict[int, float]]:
    pool: set[int] | None = None
    if robust_enabled and methods:
        voting = ensemble_voting_methods(methods, weights)
        pool = robust_ensemble_candidate_pool(
            rows_by_i, voting, robust_top_pool, robust_min_methods
        )
        if not pool:
            log.warning(
                "ensemble robust: 교집합 후보 없음 (min_methods=%d) — 전체 후보로 fallback",
                robust_min_methods,
            )
            pool = None

    if robust_aggregate == "median" and robust_enabled:
        combined = compute_ensemble_scores_median(rows_by_i, weights, pool)
    else:
        if pool is not None:
            sub = {i: rows_by_i[i] for i in pool if i in rows_by_i}
            combined = compute_ensemble_scores(sub, weights)
        else:
            combined = compute_ensemble_scores(rows_by_i, weights)

    ranked = sorted(combined.items(), key=lambda x: x[1], reverse=True)
    return [i for i, _ in ranked[:top_n]], combined


def summarize_forward_distribution(
    forward_pcts: list[float],
) -> dict[str, float]:
    arr = np.asarray(
        [x for x in forward_pcts if np.isfinite(x)],
        dtype=float,
    )
    if arr.size == 0:
        return {
            "표본수": 0,
            "승률_%": float("nan"),
            "평균_%": float("nan"),
            "중앙값_%": float("nan"),
            "표준편차_%": float("nan"),
            "최소_%": float("nan"),
            "최대_%": float("nan"),
        }
    return {
        "표본수": int(arr.size),
        "승률_%": float(np.mean(arr > 0) * 100.0),
        "평균_%": float(np.mean(arr)),
        "중앙값_%": float(np.median(arr)),
        "표준편차_%": float(np.std(arr, ddof=1)) if arr.size > 1 else 0.0,
        "최소_%": float(np.min(arr)),
        "최대_%": float(np.max(arr)),
    }


def bootstrap_forward_mean_pvalue(
    sample_pcts: list[float],
    null_pool: np.ndarray,
    n_boot: int,
    seed: int = 42,
) -> tuple[float, float]:
    """상위 유사 구간 평균 미래수익률 vs 무작위 구간 부트스트랩 p-value(우측)."""
    obs = np.asarray([x for x in sample_pcts if np.isfinite(x)], dtype=float)
    if obs.size == 0 or null_pool.size == 0:
        return float("nan"), float("nan")
    obs_mean = float(np.mean(obs))
    rng = np.random.default_rng(seed)
    n = obs.size
    boot_means = np.empty(min(n_boot, 5000), dtype=float)
    for k in range(boot_means.size):
        pick = rng.choice(null_pool, size=n, replace=True)
        boot_means[k] = float(np.mean(pick))
    p_one_sided = float(np.mean(boot_means >= obs_mean))
    return obs_mean, p_one_sided


def collect_forward_null_pool(
    price_values: np.ndarray,
    obs: int,
    target_start_idx: int,
    forward_days: int,
) -> np.ndarray:
    i_max = max_hist_start(len(price_values), obs, target_start_idx)
    out: list[float] = []
    for i in range(0, i_max + 1):
        end_i = i + obs - 1
        fr = forward_return_pct(price_values, end_i, forward_days)
        if np.isfinite(fr):
            out.append(fr)
    return np.asarray(out, dtype=float)


def format_distribution_block(
    label: str,
    stats: dict[str, float],
    obs_mean: float,
    p_value: float,
) -> str:
    lines = [f"=== {label} — 미래 {stats.get('기간', '')}거래일 수익률 분포 ==="]
    for k, v in stats.items():
        if k == "기간":
            continue
        if isinstance(v, float) and np.isfinite(v):
            lines.append(f"  {k}: {v:.4f}")
        else:
            lines.append(f"  {k}: {v}")
    if np.isfinite(obs_mean):
        lines.append(f"  표본 평균(관측): {obs_mean:.4f}%")
    if np.isfinite(p_value):
        lines.append(
            f"  부트스트랩 p-value(우측, 무작위 구간 대비): {p_value:.4f}"
        )
    return "\n".join(lines)


def build_records_for_method(
    close: pd.Series,
    price_values: np.ndarray,
    rows_by_i: dict[int, dict[str, Any]],
    ranked_is: list[int],
    method: str,
    forward_days: int,
    obs: int,
    ensemble_scores: dict[int, float] | None = None,
) -> list[SimilarityRecord]:
    method_l = method.lower()
    meta = METHOD_META.get(method_l, {})
    score_col = str(meta.get("score_col", "유사도"))
    recs: list[SimilarityRecord] = []

    for rank, i in enumerate(ranked_is, start=1):
        sim_slice = close.iloc[i : i + obs]
        end_idx = i + obs - 1
        sc = rows_by_i[i]["scores"]
        if method_l == "ensemble":
            ens = float("nan")
            if ensemble_scores is not None:
                ens = float(ensemble_scores.get(i, float("nan")))
            raw = ens
            sim = ens
        elif method_l == "dtw":
            raw = float(rows_by_i[i].get("dtw_dist", float("nan")))
            sim = float(rows_by_i[i].get("dtw_sim", distance_to_similarity(raw)))
        else:
            raw = float(sc.get(method_l, float("nan")))
            sim = raw
        fr = forward_return_pct(price_values, end_idx, forward_days)
        win_ret = pattern_return_pct(sim_slice)
        recs.append(
            SimilarityRecord(
                rank=rank,
                start_i=i,
                start_date=sim_slice.index[0].strftime("%Y-%m-%d"),
                end_date=sim_slice.index[-1].strftime("%Y-%m-%d"),
                raw_score=raw,
                similarity=sim,
                window_return_pct=win_ret,
                forward_return_pct=fr,
                method=method_l,
                score_label=score_col,
            )
        )
    return recs


def records_to_dataframe(recs: list[SimilarityRecord]) -> pd.DataFrame:
    rows = []
    for r in recs:
        row = {
            "순위": r.rank,
            "시작일": r.start_date,
            "종료일": r.end_date,
            "유사구간수익률": r.window_return_pct,
            "미래수익률": r.forward_return_pct,
        }
        if r.method == "dtw":
            row["DTW거리"] = r.raw_score
            row["DTW유사도"] = r.similarity
        elif r.method == "ensemble":
            row["ensemble점수"] = r.similarity
        else:
            row["유사도"] = r.similarity
        rows.append(row)
    return pd.DataFrame(rows)


def slice_extended(
    values: np.ndarray,
    start_i: int,
    obs: int,
    forward_days: int,
    n: int,
) -> np.ndarray:
    end_want = start_i + obs + forward_days - 1
    end_take = min(end_want, n - 1)
    return np.asarray(values[start_i : end_take + 1], dtype=float).copy()


def plot_similarity_overlay(
    close: pd.Series,
    values: np.ndarray,
    ws: WindowSpec,
    ranked_is: list[int],
    method_label: str,
    forward_days: int,
    out_path: Path,
    chart_mode: str,
) -> None:
    obs = ws.obs
    n = len(values)
    ts = ws.target_start_idx
    te = ws.target_end_idx
    target_date_str = close.index[te].strftime("%Y-%m-%d")

    t_seg = slice_extended(values, ts, obs, forward_days, n)
    y_t = normalize_chart_series(t_seg, chart_mode)
    x_t = np.arange(len(y_t))
    t_const = _is_constant(t_seg)

    fig, ax = plt.subplots(figsize=(12, 7))
    ax.plot(x_t, y_t, color="black", lw=2.8, label="Target", zorder=10)
    if t_const and chart_mode == "minmax":
        ax.text(
            0.02,
            0.02,
            "타겟: 상수 구간(min-max=0)",
            transform=ax.transAxes,
            fontsize=8,
            color="gray",
        )

    n_sim = len(ranked_is)
    cmap = plt.get_cmap("rainbow")
    colors = cmap(np.linspace(0, 0.92, max(n_sim, 1))) if n_sim else np.zeros((0, 4))

    max_len = len(y_t)
    for k, i in enumerate(ranked_is):
        seg = slice_extended(values, i, obs, forward_days, n)
        y = normalize_chart_series(seg, chart_mode)
        x = np.arange(len(y))
        max_len = max(max_len, len(y))
        lbl = close.index[i].strftime("%Y-%m-%d")
        ax.plot(x, y, color=colors[k], lw=1.1, alpha=0.88, label=lbl)

    x_right = max_len - 1
    ax.axvline(obs - 1, color="red", ls="--", lw=1.2, alpha=0.75, zorder=5)
    if max_len > obs:
        ax.axvspan(
            obs - 1,
            x_right,
            alpha=0.14,
            color="saddlebrown",
            label="미래 관찰",
        )

    ylabel = (
        "Index (start=100)"
        if chart_mode == "index100"
        else "Min-Max normalized"
    )
    ax.set_title(
        f"유사 패턴 — 타겟 {target_date_str} [{method_label}]\n"
        f"{close.name or ''} · 관찰 {obs}일 + 이후 {forward_days}일",
        fontsize=13,
    )
    ax.set_xlabel("Days")
    ax.set_ylabel(ylabel)
    ax.grid(True, alpha=0.35)
    ax.set_xlim(-0.5, max(float(x_right) + 0.5, float(obs)))
    if chart_mode == "minmax":
        ax.set_ylim(-0.02, 1.05)
    ax.legend(loc="center left", bbox_to_anchor=(1.02, 0.5), fontsize=8)
    fig.tight_layout()
    fig.savefig(out_path, dpi=165, bbox_inches="tight")
    plt.close(fig)


def execute_stumpy(
    close: pd.Series,
    ws: WindowSpec,
    ticker: str,
    mp_cfg: dict[str, Any],
    top_n_fallback: int,
    cfg_file: Path | None,
) -> tuple[AnalogResult, HistoricalAnalogEngine] | None:
    del cfg_file  # 외부 엔진 경로 미사용 (내장)
    if not _HAS_STUMPY:
        log.warning("[stumpy] stumpy 미설치 — pip install stumpy")
        return None

    top_k = int(mp_cfg.get("top_k", top_n_fallback))
    excl = float(mp_cfg.get("exclusion_zone_multiplier", 2.0))
    fwd_raw = mp_cfg.get("forward_days", [5, 10, 20, 40, 60])
    fwd_days = (
        [int(x) for x in fwd_raw]
        if isinstance(fwd_raw, list) and fwd_raw
        else [5, 10, 20, 40, 60]
    )

    q_start = close.index[ws.target_start_idx].strftime("%Y-%m-%d")
    q_end = close.index[ws.target_end_idx].strftime("%Y-%m-%d")
    df = pd.DataFrame({"close": close.values.astype(float)}, index=close.index)
    df.attrs["ticker"] = ticker

    engine = HistoricalAnalogEngine(
        forward_days=fwd_days,
        top_k=top_k,
        exclusion_zone_multiplier=excl,
    )
    try:
        result = engine.run(df, query_start=q_start, query_end=q_end)
    except ValueError as exc:
        log.warning("[stumpy] 실행 실패: %s", exc)
        return None
    return result, engine


def build_stumpy_records(
    close: pd.Series,
    price_values: np.ndarray,
    result: AnalogResult,
    obs: int,
    forward_horizon: int,
) -> tuple[list[SimilarityRecord], list[int]]:
    recs: list[SimilarityRecord] = []
    ranked_is: list[int] = []
    for a in result.analogs:
        ix = close.index.get_indexer([pd.Timestamp(a.start_date)], method=None)
        i = int(ix[0])
        if i < 0 or i + obs > len(close):
            continue
        ranked_is.append(i)
        sim_slice = close.iloc[i : i + obs]
        end_idx = i + obs - 1
        fr_raw = a.forward_returns.get(forward_horizon)
        if fr_raw is not None and np.isfinite(fr_raw):
            fr_pct = float(fr_raw) * 100.0
        else:
            fr_pct = forward_return_pct(price_values, end_idx, forward_horizon)
        win_ret = pattern_return_pct(sim_slice)
        recs.append(
            SimilarityRecord(
                rank=int(a.rank),
                start_i=i,
                start_date=sim_slice.index[0].strftime("%Y-%m-%d"),
                end_date=sim_slice.index[-1].strftime("%Y-%m-%d"),
                raw_score=float(a.distance),
                similarity=float(a.similarity_pct),
                window_return_pct=float(win_ret),
                forward_return_pct=float(fr_pct),
                method="stumpy",
                score_label="유사도",
            )
        )
    return recs, ranked_is


def build_analysis_context(raw_cfg: dict[str, Any], cfg_file: Path | None) -> AnalysisContext:
    ticker = str(raw_cfg["ticker"])
    data_start = str(raw_cfg["data_start"]).replace("-", "")
    target_raw = raw_cfg.get("target_date", "today")
    obs = int(raw_cfg["observation_days"])
    top_n = int(raw_cfg["top_n_similar"])
    forward_days = int(raw_cfg.get("forward_monitoring_days", 20))
    step = int(raw_cfg.get("similarity_scan_step_trading_days", 5))
    scan_desc_tpl = str(
        raw_cfg.get(
            "similarity_scan_description",
            "유사 후보: 거래일 간격 {step}일",
        )
    )
    out_name = str(raw_cfg.get("output_dir", "output_similarity"))
    chart_prefix = str(raw_cfg.get("chart_filename_prefix", "pattern_comparison"))
    price_col = str(raw_cfg.get("price_column", "종가"))
    strict = bool(raw_cfg.get("strict_backtest_mode", False))
    match_basis = str(raw_cfg.get("match_basis", "price")).lower()
    if match_basis not in ("price", "return"):
        match_basis = "price"
    chart_mode = str(raw_cfg.get("chart_normalization", "index100")).lower()
    if chart_mode not in ("index100", "minmax"):
        chart_mode = "index100"

    dense_cfg = raw_cfg.get("dense_rescan") or {}
    if isinstance(dense_cfg, bool):
        dense_on, dense_r, dense_m = dense_cfg, 10, 5
    elif isinstance(dense_cfg, dict):
        dense_on = bool(dense_cfg.get("enabled", False))
        dense_r = int(dense_cfg.get("radius_trading_days", 10))
        dense_m = int(dense_cfg.get("top_m", 5))
    else:
        dense_on, dense_r, dense_m = False, 10, 5

    align_cfg = raw_cfg.get("return_alignment") or {}
    if isinstance(align_cfg, bool):
        align_on, align_w = align_cfg, 0.25
    elif isinstance(align_cfg, dict):
        align_on = bool(align_cfg.get("enabled", False))
        align_w = float(align_cfg.get("weight", 0.25))
    else:
        align_on, align_w = False, 0.25

    ens_cfg = raw_cfg.get("ensemble") or {}
    if isinstance(ens_cfg, bool):
        ens_on = ens_cfg
        ens_weights = {"pearson": 0.35, "euclidean": 0.25, "dtw": 0.25, "cosine": 0.15}
    elif isinstance(ens_cfg, dict):
        ens_on = bool(ens_cfg.get("enabled", False))
        w_raw = ens_cfg.get("weights") or {}
        ens_weights = (
            {str(k).lower(): float(v) for k, v in w_raw.items()}
            if isinstance(w_raw, dict) and w_raw
            else {"pearson": 0.35, "euclidean": 0.25, "dtw": 0.25, "cosine": 0.15}
        )
    else:
        ens_on, ens_weights = False, {
            "pearson": 0.35,
            "euclidean": 0.25,
            "dtw": 0.25,
            "cosine": 0.15,
        }

    rob_cfg = ens_cfg.get("robust") if isinstance(ens_cfg, dict) else {}
    if isinstance(rob_cfg, bool):
        ens_robust_on = rob_cfg and ens_on
        ens_robust_pool, ens_robust_min, ens_robust_agg = 50, 2, "median"
    elif isinstance(rob_cfg, dict):
        ens_robust_on = bool(rob_cfg.get("enabled", ens_on)) and ens_on
        ens_robust_pool = int(rob_cfg.get("top_pool", 50))
        ens_robust_min = int(rob_cfg.get("min_methods", 2))
        ens_robust_agg = str(rob_cfg.get("aggregate", "median")).lower()
    else:
        ens_robust_on = ens_on
        ens_robust_pool, ens_robust_min, ens_robust_agg = 50, 2, "median"

    reg_cfg = raw_cfg.get("regime_filter") or {}
    if isinstance(reg_cfg, bool):
        reg_on = reg_cfg
        reg_vol, reg_trend, reg_mdd = 0.3, True, 5.0
    elif isinstance(reg_cfg, dict):
        reg_on = bool(reg_cfg.get("enabled", False))
        vol_cfg = reg_cfg.get("volatility") or {}
        reg_vol = (
            float(vol_cfg.get("max_relative_diff", 0.3))
            if isinstance(vol_cfg, dict)
            else 0.3
        )
        trend_cfg = reg_cfg.get("trend") or {}
        reg_trend = (
            bool(trend_cfg.get("require_same_sign", True))
            if isinstance(trend_cfg, dict)
            else True
        )
        dd_cfg = reg_cfg.get("drawdown") or {}
        reg_mdd = (
            float(dd_cfg.get("max_mdd_diff_pp", 5.0))
            if isinstance(dd_cfg, dict)
            else 5.0
        )
    else:
        reg_on, reg_vol, reg_trend, reg_mdd = False, 0.3, True, 5.0

    dist_cfg = raw_cfg.get("forward_distribution") or {}
    if isinstance(dist_cfg, bool):
        dist_on = dist_cfg
        n_boot = 500
    elif isinstance(dist_cfg, dict):
        dist_on = bool(dist_cfg.get("enabled", True))
        n_boot = int(dist_cfg.get("bootstrap_samples", 500))
    else:
        dist_on, n_boot = True, 500

    dtw_cfg = raw_cfg.get("dtw") or {}
    dtw_window_ratio = float(
        dtw_cfg.get("window_ratio", 0.1) if isinstance(dtw_cfg, dict) else 0.1
    )

    methods_raw = [m.lower() for m in raw_cfg["similarity_methods"]]
    use_dtw_flag = bool(raw_cfg.get("use_dtw", False))
    dtw_listed = "dtw" in methods_raw
    use_dtw = (use_dtw_flag or dtw_listed) and _HAS_DTW
    if use_dtw_flag and not _HAS_DTW:
        log.warning("use_dtw=true 이지만 dtaidistance 미설치 — DTW 생략")
    if dtw_listed and not _HAS_DTW:
        log.warning("similarity_methods 에 dtw 있으나 dtaidistance 미설치")

    methods: list[str] = []
    seen_stumpy = False
    for m in methods_raw:
        if m in STUMPY_ALIASES:
            if not seen_stumpy:
                methods.append("stumpy")
                seen_stumpy = True
            continue
        if m == "dtw" and not use_dtw:
            continue
        methods.append(m)

    mp_cfg = raw_cfg.get("matrix_profile")
    matrix_profile_cfg = mp_cfg if isinstance(mp_cfg, dict) else {}

    cfg_pass = {
        "ticker": ticker,
        "data_start": data_start,
        "price_column": price_col,
    }
    close = fetch_close(cfg_pass)
    close.name = ticker

    target_ts = resolve_trading_date(close.index, target_raw)
    if strict:
        close = close.loc[:target_ts]
        log.info("strict_backtest_mode: 데이터를 %s 까지 절단", target_ts.date())

    price_values = close.values.astype(float)
    values = build_match_series(close, match_basis)
    ws = window_spec(close, target_ts, obs)
    if ws.target_start_idx < obs:
        raise ValueError(
            "타겟과 겹치지 않는 유사 구간을 만들 수 없습니다. "
            "data_start 를 앞당기거나 observation_days 를 줄이세요."
        )

    target_vec = values[ws.target_slice]
    target_norm = safe_zscore(target_vec)
    target_win_ret = pattern_return_pct(close.iloc[ws.target_slice])

    out_dir = _project_root() / out_name
    out_dir.mkdir(parents=True, exist_ok=True)
    date_tag = close.index[ws.target_end_idx].strftime("%Y%m%d")

    return AnalysisContext(
        ticker=ticker,
        close=close,
        values=values,
        ws=ws,
        target_norm=target_norm,
        target_ts=target_ts,
        forward_days=forward_days,
        obs=obs,
        out_dir=out_dir,
        date_tag=date_tag,
        methods=methods,
        matrix_profile_cfg=matrix_profile_cfg,
        scan_step=step,
        scan_description=scan_desc_tpl.replace("{step}", str(step)),
        use_dtw=use_dtw,
        dtw_window_ratio=dtw_window_ratio,
        chart_mode=chart_mode,  # type: ignore[arg-type]
        match_basis=match_basis,  # type: ignore[arg-type]
        strict_backtest=strict,
        dense_rescan=dense_on,
        dense_radius=dense_r,
        dense_top_m=dense_m,
        top_n_similar=top_n,
        chart_prefix=chart_prefix,
        save_csv=bool(raw_cfg.get("save_table_csv", True)),
        save_txt=bool(raw_cfg.get("save_table_txt", True)),
        save_md=bool(raw_cfg.get("save_table_md", True)),
        price_values=price_values,
        ensemble_enabled=ens_on,
        ensemble_weights=ens_weights,
        distribution_enabled=dist_on,
        bootstrap_samples=n_boot,
        target_window_return_pct=float(target_win_ret),
        return_alignment_enabled=align_on,
        return_alignment_weight=align_w,
        regime_filter_enabled=reg_on,
        regime_vol_max_relative_diff=reg_vol,
        regime_trend_require_same_sign=reg_trend,
        regime_mdd_max_diff_pp=reg_mdd,
        ensemble_robust_enabled=ens_robust_on,
        ensemble_robust_top_pool=ens_robust_pool,
        ensemble_robust_min_methods=ens_robust_min,
        ensemble_robust_aggregate=ens_robust_agg,
    )


def filter_stumpy_result_by_regime(
    close: pd.Series,
    result: AnalogResult,
    obs: int,
    target_regime: RegimeFeatures,
    vol_max_relative_diff: float,
    trend_require_same_sign: bool,
    mdd_max_diff_pp: float,
) -> AnalogResult:
    kept: list[HistoricalAnalog] = []
    for a in result.analogs:
        ix = close.index.get_indexer([pd.Timestamp(a.start_date)], method=None)
        i = int(ix[0])
        if i < 0 or i + obs > len(close):
            continue
        feat = compute_regime_features(close.iloc[i : i + obs])
        if passes_regime_filter(
            target_regime,
            feat,
            vol_max_relative_diff,
            trend_require_same_sign,
            mdd_max_diff_pp,
        ):
            kept.append(a)
    return replace(result, analogs=kept)


def run_method_reports(ctx: AnalysisContext, cfg_file: Path | None) -> None:
    target_regime: RegimeFeatures | None = None
    if ctx.regime_filter_enabled:
        target_regime = compute_regime_features(
            ctx.close.iloc[ctx.ws.target_slice]
        )

    rows_by_i = scan_with_optional_dense(
        ctx.close,
        ctx.values,
        ctx.target_norm,
        ctx.obs,
        ctx.ws.target_start_idx,
        ctx.methods,
        ctx.use_dtw,
        ctx.scan_step,
        ctx.dense_rescan,
        ctx.dense_radius,
        ctx.dense_top_m,
        ctx.dtw_window_ratio,
        regime_enabled=ctx.regime_filter_enabled,
        target_regime=target_regime,
        regime_vol_max_relative_diff=ctx.regime_vol_max_relative_diff,
        regime_trend_require_same_sign=ctx.regime_trend_require_same_sign,
        regime_mdd_max_diff_pp=ctx.regime_mdd_max_diff_pp,
    )
    rows_list = list(rows_by_i.values())

    report_txt: list[str] = []
    report_md: list[str] = []

    te = ctx.ws.target_end_idx
    last_sim_i = ctx.ws.target_start_idx - ctx.obs
    header_lines = [
        "=== 타겟 구간 ===",
        (
            f"티커: {ctx.ticker} | 타겟 종료: "
            f"{ctx.close.index[te].strftime('%Y-%m-%d')} | "
            f"관찰 {ctx.obs}거래일 | match_basis={ctx.match_basis}"
        ),
        f"타겟 관찰 수익률: {ctx.target_window_return_pct:.4f}%",
        INTERPRETATION_HEADER,
        ctx.scan_description,
    ]
    if ctx.match_basis == "return":
        header_lines.append(
            "※ match_basis=return: 유사도는 일일 수익률 패턴 기준이라 "
            "관찰 구간 누적 수익률이 타겟과 다를 수 있습니다. "
            "2.main.py 와 비슷하게 맞추려면 match_basis: price 를 쓰세요."
        )
    if ctx.return_alignment_enabled:
        header_lines.append(
            f"※ return_alignment: ON (weight={ctx.return_alignment_weight}) "
            "— 패턴 유사도에 관찰 수익률 근접도를 반영합니다."
        )
    if ctx.regime_filter_enabled:
        header_lines.append(
            "※ regime_filter: ON — 변동성(σ 상대차), 추세(누적수익 부호), "
            f"MDD(차이 ≤ {ctx.regime_mdd_max_diff_pp}%p) 기준으로 후보를 제한합니다."
        )
    if ctx.strict_backtest:
        header_lines.append(
            f"strict_backtest_mode: ON (데이터 종료 ≤ {ctx.target_ts.date()})"
        )
    if last_sim_i >= 0:
        header_lines.append(
            f"유사 구간 마지막 시작일: "
            f"{ctx.close.index[last_sim_i].strftime('%Y-%m-%d')}"
        )

    header = "\n".join(header_lines)
    print("\n" + header + "\n")
    report_txt.append(header)
    report_md.append(f"# 유사 패턴 분석\n\n```\n{header}\n```\n")

    top_n = ctx.top_n_similar
    price = ctx.price_values

    def emit_method_output(
        method_key: str,
        label: str,
        recs: list[SimilarityRecord],
        ranked_is: list[int],
    ) -> None:
        slug = "stumpy" if method_key == "stumpy" else method_key
        dfm = records_to_dataframe(recs)
        tbl = format_dataframe_table(dfm)
        sec = f"\n방법론: {label}\n{tbl}\n"
        print(sec)
        report_txt.append(sec.strip())
        note = ""
        if method_key == "dtw":
            note = (
                "\n\n> **DTW:** `DTW거리`는 작을수록 유사. "
                "`DTW유사도`는 1/(1+거리).\n"
            )
        if method_key == "ensemble":
            if ctx.ensemble_robust_enabled:
                note = (
                    "\n\n> **Ensemble (robust):** 각 방법 TOP-"
                    f"{ctx.ensemble_robust_top_pool} 안에 "
                    f"{ctx.ensemble_robust_min_methods}개 이상 포함된 구간만 대상, "
                    f"정규화 점수 {ctx.ensemble_robust_aggregate}.\n"
                )
            else:
                note = (
                    "\n\n> **Ensemble:** 방법별 min-max 정규화 후 가중 합산.\n"
                )
        report_md.append(f"## {label}\n\n{dataframe_to_markdown(dfm)}{note}\n")
        if ctx.save_csv:
            csv_path = ctx.out_dir / f"table_{slug}_{ctx.date_tag}.csv"
            dfm.to_csv(csv_path, index=False, encoding="utf-8-sig")
            log.info("표 CSV: %s", csv_path)
        png = ctx.out_dir / f"{ctx.chart_prefix}_{slug}_{ctx.date_tag}.png"
        plot_similarity_overlay(
            ctx.close,
            price,
            ctx.ws,
            ranked_is,
            label,
            ctx.forward_days,
            png,
            ctx.chart_mode,
        )
        log.info("[%s] 차트: %s", method_key, png)
        return recs

    for method in ctx.methods:
        slug = "stumpy" if method == "stumpy" else method
        label = METHOD_META.get(method, {}).get("label", method)

        if method == "stumpy":
            pair = execute_stumpy(
                ctx.close,
                ctx.ws,
                ctx.ticker,
                ctx.matrix_profile_cfg,
                top_n,
                cfg_file,
            )
            if pair is None:
                log.warning("[%s] 결과 없음", slug)
                continue
            result, _ = pair
            if not result.analogs:
                log.warning("[%s] 유사 구간 없음", slug)
                continue
            if ctx.regime_filter_enabled and target_regime is not None:
                result = filter_stumpy_result_by_regime(
                    ctx.close,
                    result,
                    ctx.obs,
                    target_regime,
                    ctx.regime_vol_max_relative_diff,
                    ctx.regime_trend_require_same_sign,
                    ctx.regime_mdd_max_diff_pp,
                )
                if not result.analogs:
                    log.warning("[%s] regime 필터 후 유사 구간 없음", slug)
                    continue
            recs, ranked_is = build_stumpy_records(
                ctx.close,
                price,
                result,
                ctx.obs,
                ctx.forward_days,
            )
        else:
            if ctx.return_alignment_enabled and method != "dtw":
                ranked_is = rank_indices_with_return_alignment(
                    rows_list,
                    method,
                    top_n,
                    ctx.close,
                    ctx.obs,
                    ctx.target_window_return_pct,
                    ctx.return_alignment_weight,
                )
            else:
                ranked_is = rank_indices(rows_list, method, top_n)
            if not ranked_is:
                log.warning("[%s] 유효 후보 없음", method)
                continue
            recs = build_records_for_method(
                ctx.close,
                price,
                rows_by_i,
                ranked_is,
                method,
                ctx.forward_days,
                ctx.obs,
            )

        emit_method_output(method, str(label), recs, ranked_is)

    if ctx.ensemble_enabled and rows_by_i:
        ens_weights = {
            k: v
            for k, v in ctx.ensemble_weights.items()
            if k in METHOD_META or k == "dtw"
        }
        ens_ranked, ens_combined = rank_indices_ensemble(
            rows_by_i,
            ens_weights,
            top_n,
            methods=ctx.methods,
            robust_enabled=ctx.ensemble_robust_enabled,
            robust_top_pool=ctx.ensemble_robust_top_pool,
            robust_min_methods=ctx.ensemble_robust_min_methods,
            robust_aggregate=ctx.ensemble_robust_aggregate,
        )
        if ens_ranked:
            ens_recs = build_records_for_method(
                ctx.close,
                price,
                rows_by_i,
                ens_ranked,
                "ensemble",
                ctx.forward_days,
                ctx.obs,
                ensemble_scores=ens_combined,
            )
            emit_method_output("ensemble", "Ensemble", ens_recs, ens_ranked)

            if ctx.distribution_enabled:
                null_pool = collect_forward_null_pool(
                    price,
                    ctx.obs,
                    ctx.ws.target_start_idx,
                    ctx.forward_days,
                )
                fwd_list = [r.forward_return_pct for r in ens_recs]
                stats = summarize_forward_distribution(fwd_list)
                stats["기간"] = float(ctx.forward_days)
                obs_mean, p_val = bootstrap_forward_mean_pvalue(
                    fwd_list,
                    null_pool,
                    ctx.bootstrap_samples,
                )
                dist_block = format_distribution_block(
                    "Ensemble TOP 유사구간",
                    stats,
                    obs_mean,
                    p_val,
                )
                print("\n" + dist_block + "\n")
                report_txt.append(dist_block)
                report_md.append(
                    f"## 미래수익률 분포 (Ensemble)\n\n```\n{dist_block}\n```\n"
                )
                dist_df = pd.DataFrame([stats])
                dist_path = (
                    ctx.out_dir
                    / f"forward_distribution_ensemble_{ctx.date_tag}.csv"
                )
                dist_df.to_csv(dist_path, index=False, encoding="utf-8-sig")
                log.info("분포 CSV: %s", dist_path)

    if ctx.save_txt and report_txt:
        txt_path = ctx.out_dir / f"results_tables_{ctx.date_tag}.txt"
        txt_path.write_text("\ufeff" + "\n\n".join(report_txt), encoding="utf-8")
        log.info("통합 TXT: %s", txt_path)

    if ctx.save_md and report_md:
        md_path = ctx.out_dir / f"results_tables_{ctx.date_tag}.md"
        md_path.write_text("\n\n".join(report_md), encoding="utf-8")
        log.info("통합 MD: %s", md_path)


def run_stumpy_detail_report(
    ctx: AnalysisContext,
    cfg_file: Path | None,
    report_txt: list[str],
    report_md: list[str],
) -> None:
    pair = execute_stumpy(
        ctx.close,
        ctx.ws,
        ctx.ticker,
        ctx.matrix_profile_cfg,
        ctx.top_n_similar,
        cfg_file,
    )
    if pair is None:
        return
    result, engine = pair
    buf = io.StringIO()
    with redirect_stdout(buf):
        engine.print_report(result)
    mp_text = buf.getvalue().rstrip() + "\n"
    print(mp_text)
    report_txt.append(mp_text.strip())
    report_md.append(
        "## Matrix Profile (STUMPY)\n\n```\n" + mp_text.strip() + "\n```\n"
    )
    if bool(ctx.matrix_profile_cfg.get("save_report_txt", True)):
        p = ctx.out_dir / f"matrix_profile_stumpy_{ctx.date_tag}.txt"
        p.write_text("\ufeff" + mp_text, encoding="utf-8")


def main(argv: list[str] | None = None) -> None:
    argv = argv or sys.argv[1:]
    cfg_path = Path(argv[0]) if argv else None
    raw = load_config(cfg_path)
    setup_logging(str(raw.get("log_level", "INFO")))
    configure_stdio_utf8()

    ctx = build_analysis_context(raw, cfg_path)
    run_method_reports(ctx, cfg_path)

    if bool(ctx.matrix_profile_cfg.get("enabled", False)) and "stumpy" not in ctx.methods:
        extra_txt: list[str] = []
        extra_md: list[str] = []
        run_stumpy_detail_report(ctx, cfg_path, extra_txt, extra_md)


if __name__ == "__main__":
    main()
