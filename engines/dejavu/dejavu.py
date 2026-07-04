"""
dejavu — 독립 유사도 트랙 (STUMPY 없음).

1. 주가 z-score → 1-1 Pearson | 1-2 DTW
2. 로그수익률 → 2-1 Pearson(원시) | 2-2 DTW(z-score)
3. 주가 이동평균(ma_windows) → z-score → 3-1 Pearson | 3-2 DTW

각 트랙별 TOP N 표·차트를 독립 저장. 수익률·차트 오버레이는 원 종가(%).

실행: python dejavu.py [dejavu.yml]
"""

from __future__ import annotations

import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

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
from scipy.stats import pearsonr

try:
    from dtaidistance import dtw as dtw_mod

    _DTW_BACKEND = "dtaidistance"
except ImportError:
    dtw_mod = None  # type: ignore[misc, assignment]
    try:
        from fastdtw import fastdtw as _fastdtw
        from scipy.spatial.distance import euclidean as _euclidean

        _DTW_BACKEND = "fastdtw"
    except ImportError:
        _fastdtw = None  # type: ignore[misc, assignment]
        _euclidean = None  # type: ignore[misc, assignment]
        _DTW_BACKEND = None

_HAS_DTW = _DTW_BACKEND is not None

# 시인성 개선 차트 — 순위별 고정 색·굵기
RANK_COLORS = ("#2563EB", "#EA580C", "#16A34A", "#9333EA", "#DC2626")
RANK_LINEWIDTHS = (2.0, 1.35, 1.35, 1.15, 1.15)
RANK_ALPHAS = (1.0, 0.88, 0.88, 0.72, 0.72)

METHODOLOGY_NOTES = """
【dejavu — 트랙 독립】
  1-1: 종가 z-score → Pearson | 1-2: 종가 z-score → DTW
  2-1: 로그수익률(원시) → Pearson | 2-2: 로그 z-score → DTW
  3-1/3-2: 종가 MA({ma_w}) → z-score → Pearson / DTW (w별 최대·최소)
  수익률·차트: 원 종가(%)
"""

@dataclass(frozen=True)
class TrackSpec:
    key: str
    slug: str
    label: str
    higher_is_better: bool
    needs_dtw: bool


TRACK_SPECS: tuple[TrackSpec, ...] = (
    TrackSpec("price_zscore_pearson", "1_1_price_zscore_pearson", "1-1 주가 z-score · Pearson", True, False),
    TrackSpec("price_zscore_dtw", "1_2_price_zscore_dtw", "1-2 주가 z-score · DTW", False, True),
    TrackSpec("log_pearson", "2_1_log_pearson", "2-1 로그수익률 · Pearson", True, False),
    TrackSpec("log_zscore_dtw", "2_2_log_zscore_dtw", "2-2 로그수익률 z-score · DTW", False, True),
    TrackSpec("ma_zscore_pearson", "3_1_ma_zscore_pearson", "3-1 주가 MA z-score · Pearson", True, False),
    TrackSpec("ma_zscore_dtw", "3_2_ma_zscore_dtw", "3-2 주가 MA z-score · DTW", False, True),
)


def _project_root() -> Path:
    return Path(__file__).resolve().parent


SNAPATCH_ROOT = _project_root().parent.parent


def _resolve_output_dir(out_name: str) -> Path:
    """output_dir 을 snapatch 루트 기준으로 해석 (outputs/ 통합)."""
    raw = Path(out_name)
    if raw.is_absolute():
        return raw
    normalized = out_name.replace("\\", "/").strip("/")
    if normalized == "output_dejavu":
        return SNAPATCH_ROOT / "outputs" / "dejavu"
    if normalized.startswith("outputs/"):
        return SNAPATCH_ROOT / normalized
    return _project_root() / out_name


# --- 공용 유틸 (dejavu 단독 실행용) ---


def configure_stdio_utf8() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError, AttributeError):
                pass


def format_dataframe_table(df: pd.DataFrame) -> str:
    disp = df.copy()
    for col in disp.columns:
        if pd.api.types.is_float_dtype(disp[col]):
            disp[col] = disp[col].map(
                lambda x: ""
                if x is None
                or (isinstance(x, (float, np.floating)) and (np.isnan(x) or np.isinf(x)))
                else f"{float(x):.4f}"
            )
    return disp.to_string(index=False)


def dataframe_to_markdown(df: pd.DataFrame) -> str:
    disp = df.copy()
    for col in disp.columns:
        if pd.api.types.is_float_dtype(disp[col]):
            disp[col] = disp[col].map(
                lambda x: ""
                if x is None
                or (isinstance(x, (float, np.floating)) and (np.isnan(x) or np.isinf(x)))
                else f"{float(x):.4f}"
            )
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
        cfg_path = root / "dejavu.yml"
        if not cfg_path.is_file():
            alt = root / "dejavu.yaml"
            if alt.is_file():
                cfg_path = alt
    if not cfg_path.is_file():
        raise FileNotFoundError(
            f"설정 파일이 없습니다: {cfg_path} (dejavu.yml 을 두세요.)"
        )
    with cfg_path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError("YAML 루트는 키-값 매핑(객체)이어야 합니다.")
    return data


def safe_zscore(values: np.ndarray) -> np.ndarray:
    std = float(np.std(values))
    if std == 0.0:
        return np.zeros_like(values, dtype=float)
    return (values - float(np.mean(values))) / std


def safe_minmax(values: np.ndarray) -> np.ndarray:
    lo, hi = float(np.min(values)), float(np.max(values))
    if hi == lo:
        return np.zeros_like(values, dtype=float)
    return (values - lo) / (hi - lo)


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


def _is_constant(arr: np.ndarray) -> bool:
    flat = arr.reshape(-1)
    if flat.size == 0:
        return True
    return bool(np.allclose(flat, flat[0], equal_nan=True))


def _ensure_krx_ready() -> None:
    """snapatch 통합: engines/match krx_io 로 타임아웃·KRX 세션 적용."""
    try:
        from krx_io import (
            REQUEST_TIMEOUT_SEC,
            _apply_krx_session,
            patch_requests_default_timeout,
        )

        patch_requests_default_timeout(REQUEST_TIMEOUT_SEC)
        login_id = (os.getenv("KRX_ID") or "").strip()
        login_pw = (os.getenv("KRX_PW") or "").strip()
        if login_id and login_pw:
            _apply_krx_session(login_id, login_pw)
    except ImportError:
        pass


_krx_ready = False


def fetch_close(cfg: dict[str, Any]) -> pd.Series:
    global _krx_ready
    if not _krx_ready:
        _ensure_krx_ready()
        _krx_ready = True
    start = str(cfg["data_start"]).replace("-", "")
    end = datetime.now().strftime("%Y%m%d")
    ticker = cfg["ticker"]
    col = cfg.get("price_column", "종가")
    df = stock.get_market_ohlcv_by_date(start, end, ticker)
    if col not in df.columns:
        raise KeyError(f"컬럼 없음: {col} / 사용 가능: {list(df.columns)}")
    s = df[col].astype(float).copy()
    s.index = pd.to_datetime(s.index)
    s = s.sort_index()
    s = s[~s.index.duplicated(keep="last")]
    return s


@dataclass(frozen=True)
class WindowSpec:
    target_end_idx: int
    obs: int
    target_start_idx: int

    @property
    def target_slice(self) -> slice:
        return slice(self.target_start_idx, self.target_end_idx + 1)


def window_spec(close: pd.Series, target_ts: pd.Timestamp, obs: int) -> WindowSpec:
    if obs < 3:
        raise ValueError("observation_days 는 3 이상이어야 합니다.")
    if target_ts not in close.index:
        raise KeyError(f"타겟일이 데이터에 없습니다: {target_ts}")
    end_idx = int(close.index.get_loc(target_ts))
    start_idx = end_idx - obs + 1
    if start_idx < 0:
        raise ValueError(
            f"데이터가 부족합니다. 종가 {len(close)}일, 관찰 {obs}일 필요."
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


def forward_return_pct(values: np.ndarray, end_idx: int, horizon: int) -> float:
    j = end_idx + horizon
    if j >= len(values) or end_idx < 0:
        return float("nan")
    a = float(values[end_idx])
    b = float(values[j])
    if a == 0:
        return float("nan")
    return (b / a - 1.0) * 100.0


def dtw_distance(a: np.ndarray, b: np.ndarray) -> float:
    if not _HAS_DTW:
        return float("nan")
    x = a.astype(np.double).reshape(-1)
    y = b.astype(np.double).reshape(-1)
    if _DTW_BACKEND == "dtaidistance" and dtw_mod is not None:
        return float(dtw_mod.distance(x, y))
    if _DTW_BACKEND == "fastdtw" and _fastdtw is not None and _euclidean is not None:
        dist, _ = _fastdtw(x.reshape(-1, 1), y.reshape(-1, 1), dist=_euclidean)
        return float(dist)
    return float("nan")


def max_hist_start(close_len: int, obs: int, target_start_idx: int) -> int:
    cap_by_data = close_len - obs
    cap_by_target = target_start_idx - obs
    return max(0, min(cap_by_data, cap_by_target))


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


# --- dejavu 트랙 ---


def build_ma_series_strict(close: pd.Series, window: int) -> np.ndarray:
    """단순 MA — min_periods 미달 구간은 NaN (bfill 없음)."""
    w = max(3, int(window))
    ma = close.astype(float).rolling(window=w, min_periods=w).mean()
    return ma.values.astype(float).reshape(-1)


def _parse_window_list(raw: Any, default: tuple[int, ...]) -> tuple[int, ...]:
    if raw is None:
        return default
    if isinstance(raw, int):
        return (max(3, raw),)
    if isinstance(raw, (list, tuple)):
        out = sorted({max(3, int(x)) for x in raw})
        return tuple(out) if out else default
    return default


def build_log_returns(close: pd.Series) -> np.ndarray:
    """일별 로그수익률 ln(P_t/P_{t-1}), 인덱스 0은 0."""
    c = close.astype(float).values.reshape(-1)
    out = np.zeros(len(c), dtype=float)
    if len(c) < 2:
        return out
    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = c[1:] / c[:-1]
        out[1:] = np.log(np.where(ratio > 0, ratio, np.nan))
    return np.nan_to_num(out, nan=0.0, posinf=0.0, neginf=0.0)


def segment_finite(seg: np.ndarray, obs: int) -> bool:
    return seg.size == obs and bool(np.all(np.isfinite(seg)))


def pearson_raw(a: np.ndarray, b: np.ndarray) -> float:
    flat_a = a.reshape(-1)
    flat_b = b.reshape(-1)
    if _is_constant(flat_a) or _is_constant(flat_b):
        return float("nan")
    pr, _ = pearsonr(flat_a, flat_b)
    return float(pr) if np.isfinite(pr) else float("nan")


def resolve_warmup(
    min_warmup_cfg: Any,
    ma_windows: tuple[int, ...],
    need_ma_warmup: bool,
) -> int:
    auto_need = 1
    if need_ma_warmup and ma_windows:
        auto_need = max(auto_need, max(ma_windows))
    if isinstance(min_warmup_cfg, str) and min_warmup_cfg.lower() == "auto":
        return auto_need
    if min_warmup_cfg is None:
        return auto_need
    try:
        return max(auto_need, max(1, int(min_warmup_cfg)))
    except (TypeError, ValueError):
        return auto_need


@dataclass(frozen=True)
class PipelineConfig:
    enabled: bool = True
    track_enabled: dict[str, bool] = field(default_factory=dict)
    ma_windows: tuple[int, ...] = (5, 10, 20)
    min_warmup_trading_days: Any = "auto"
    emit_tracks: bool = True


@dataclass
class RunContext:
    ticker: str
    close: pd.Series
    values_price: np.ndarray
    values_log: np.ndarray
    target_price_z: np.ndarray
    target_log_raw: np.ndarray
    target_log_z: np.ndarray
    ws: WindowSpec
    forward_days: int
    obs: int
    top_n: int
    scan_step: int
    scan_desc: str
    i_min: int
    out_dir: Path
    date_tag: str
    chart_prefix: str
    save_csv: bool
    save_txt: bool
    save_md: bool
    use_dtw: bool
    ma_windows: tuple[int, ...]
    ma_windows_label: str
    ma_series: dict[int, np.ndarray]
    target_ma_z: dict[int, np.ndarray]


@dataclass
class StageScores:
    raw: dict[int, float] = field(default_factory=dict)
    ranks: dict[int, int] = field(default_factory=dict)


@dataclass
class PipelineOutcome:
    tracks: dict[str, StageScores]


def _default_config_path() -> Path:
    root = _project_root()
    for name in ("dejavu.yml", "dejavu.yaml"):
        p = root / name
        if p.is_file():
            return p
    return root / "dejavu.yml"


def load_dejavu_config(path: Path | None = None) -> dict[str, Any]:
    if path is not None:
        return load_config(path)
    p = _default_config_path()
    if p.is_file():
        return load_config(p)
    return load_config(path)


def parse_pipeline_config(raw: dict[str, Any]) -> PipelineConfig:
    p = raw.get("pipeline_dejavu") or raw.get("pipeline_01") or {}
    if isinstance(p, bool):
        return PipelineConfig(enabled=p)
    if not isinstance(p, dict):
        p = {}

    track_raw = p.get("tracks") or {}
    track_enabled: dict[str, bool] = {}
    if isinstance(track_raw, dict):
        for spec in TRACK_SPECS:
            if spec.key in track_raw:
                track_enabled[spec.key] = bool(track_raw[spec.key])

    ma_windows = _parse_window_list(
        p.get("ma_windows", p.get("ma_price_windows")),
        (5, 10, 20),
    )

    legacy = {
        "price_zscore_pearson": p.get("track_1_1", p.get("price_zscore_pearson")),
        "price_zscore_dtw": p.get("track_1_2", p.get("price_zscore_dtw")),
        "log_pearson": p.get("track_2_1", p.get("log_pearson", p.get("pearson_on_raw_log"))),
        "log_zscore_dtw": p.get(
            "track_2_2", p.get("log_zscore_dtw", p.get("dtw_on_zscore_log"))
        ),
        "ma_zscore_pearson": p.get("track_3_1", p.get("ma_zscore_pearson")),
        "ma_zscore_dtw": p.get("track_3_2", p.get("ma_zscore_dtw")),
    }
    for key, val in legacy.items():
        if val is not None and key not in track_enabled:
            track_enabled[key] = bool(val)

    return PipelineConfig(
        enabled=bool(p.get("enabled", True)),
        track_enabled=track_enabled,
        ma_windows=ma_windows,
        min_warmup_trading_days=p.get("min_warmup_trading_days", "auto"),
        emit_tracks=bool(p.get("emit_tracks", p.get("emit_stage_tables", True))),
    )


def ma_tracks_requested(pipe: PipelineConfig) -> bool:
    return is_track_enabled(pipe, "ma_zscore_pearson") or is_track_enabled(
        pipe, "ma_zscore_dtw"
    )


def is_track_enabled(pipe: PipelineConfig, key: str) -> bool:
    if key in pipe.track_enabled:
        return bool(pipe.track_enabled[key])
    return True


def _validate_target_slices(ctx: RunContext) -> None:
    sl = ctx.ws.target_slice
    tgt_p = np.asarray(ctx.values_price[sl], dtype=float)
    if not segment_finite(tgt_p, ctx.obs):
        raise ValueError("타겟 관찰 구간 종가가 유효하지 않습니다.")
    if not segment_finite(ctx.target_price_z, ctx.obs):
        raise ValueError("타겟 종가 z-score 구간이 유효하지 않습니다.")
    if not segment_finite(ctx.target_log_raw, ctx.obs):
        raise ValueError("타겟 관찰 구간 로그수익률이 유효하지 않습니다.")
    if not segment_finite(ctx.target_log_z, ctx.obs):
        raise ValueError("타겟 로그수익률 z-score 구간이 유효하지 않습니다.")
    for w in ctx.ma_windows:
        if w in ctx.target_ma_z and not segment_finite(ctx.target_ma_z[w], ctx.obs):
            raise ValueError(
                f"타겟 MA({w}) z-score 구간이 유효하지 않습니다. "
                "data_start 를 앞당기거나 ma_windows 를 줄이세요."
            )


def build_run_context(raw: dict[str, Any], pipe: PipelineConfig) -> RunContext:
    ticker = str(raw["ticker"])
    data_start = str(raw["data_start"]).replace("-", "")
    target_raw = raw.get("target_date", "today")
    obs = int(raw["observation_days"])
    top_n = int(raw["top_n_similar"])
    forward_days = int(raw.get("forward_monitoring_days", 20))
    step = int(raw.get("similarity_scan_step_trading_days", 5))
    scan_tpl = str(
        raw.get(
            "similarity_scan_description",
            "유사 구간 후보: 거래일 기준 시작 간격 {step}일",
        )
    )
    out_name = str(raw.get("output_dir", "output_dejavu"))
    chart_prefix = str(raw.get("chart_filename_prefix", "pattern_comparison_dejavu"))
    price_col = str(raw.get("price_column", "종가"))

    methods_raw = [str(x).lower() for x in raw.get("similarity_methods", [])]
    use_dtw_flag = bool(raw.get("use_dtw", False))
    use_dtw = (use_dtw_flag or "dtw" in methods_raw) and _HAS_DTW

    close = fetch_close(
        {"ticker": ticker, "data_start": data_start, "price_column": price_col}
    )
    close.name = ticker
    target_ts = resolve_trading_date(close.index, target_raw)
    ws = window_spec(close, target_ts, obs)
    if ws.target_start_idx < obs:
        raise ValueError(
            "타겟과 겹치지 않는 유사 구간을 만들 수 없습니다. "
            "data_start 를 앞당기거나 observation_days 를 줄이세요."
        )

    values_price = close.values.astype(float).reshape(-1)
    values_log = build_log_returns(close)
    sl = ws.target_slice
    target_price_raw = np.asarray(values_price[sl], dtype=float)
    target_price_z = safe_zscore(target_price_raw)
    target_log_raw = np.asarray(values_log[sl], dtype=float)
    target_log_z = safe_zscore(target_log_raw)

    ma_series: dict[int, np.ndarray] = {}
    target_ma_z: dict[int, np.ndarray] = {}
    effective_ma: list[int] = []
    if ma_tracks_requested(pipe):
        for w in pipe.ma_windows:
            ma_arr = build_ma_series_strict(close, w)
            tgt_raw = np.asarray(ma_arr[sl], dtype=float)
            if not segment_finite(tgt_raw, obs) or _is_constant(tgt_raw):
                print(
                    f"경고: MA({w}) 타겟 구간 무효 — 워밍업 부족 또는 상수, 해당 w 제외"
                )
                continue
            ma_series[w] = ma_arr
            target_ma_z[w] = safe_zscore(tgt_raw)
            effective_ma.append(w)
        if not effective_ma:
            raise ValueError(
                "MA 트랙이 활성화되었으나 유효한 ma_windows 가 없습니다. "
                "data_start 를 앞당기거나 ma_windows 를 조정하세요."
            )

    need_ma_warmup = bool(effective_ma)
    warmup = resolve_warmup(
        pipe.min_warmup_trading_days,
        tuple(effective_ma),
        need_ma_warmup,
    )
    ma_label = ",".join(str(w) for w in effective_ma) or "-"
    out_dir = _resolve_output_dir(out_name)
    out_dir.mkdir(parents=True, exist_ok=True)
    date_tag = close.index[ws.target_end_idx].strftime("%Y%m%d")

    ctx = RunContext(
        ticker=ticker,
        close=close,
        values_price=values_price,
        values_log=values_log,
        target_price_z=target_price_z,
        target_log_raw=target_log_raw,
        target_log_z=target_log_z,
        ws=ws,
        forward_days=forward_days,
        obs=obs,
        top_n=top_n,
        scan_step=step,
        scan_desc=scan_tpl.replace("{step}", str(step)),
        i_min=warmup,
        out_dir=out_dir,
        date_tag=date_tag,
        chart_prefix=chart_prefix,
        save_csv=bool(raw.get("save_table_csv", True)),
        save_txt=bool(raw.get("save_table_txt", True)),
        save_md=bool(raw.get("save_table_md", True)),
        use_dtw=use_dtw,
        ma_windows=tuple(effective_ma),
        ma_windows_label=ma_label,
        ma_series=ma_series,
        target_ma_z=target_ma_z,
    )
    _validate_target_slices(ctx)
    return ctx


def assign_ranks(scores: dict[int, float], higher_is_better: bool) -> dict[int, int]:
    valid = [(i, s) for i, s in scores.items() if np.isfinite(s)]
    if not valid:
        return {}
    valid.sort(key=lambda x: x[1], reverse=higher_is_better)
    return {i: rank for rank, (i, _) in enumerate(valid, start=1)}


def scan_similarity(
    ctx: RunContext,
    score_fn: Callable[[int], float],
    label: str,
    higher_is_better: bool,
) -> StageScores:
    i_max = max_hist_start(len(ctx.values_price), ctx.obs, ctx.ws.target_start_idx)
    step = max(1, ctx.scan_step)
    scores: dict[int, float] = {}
    for i in range(ctx.i_min, i_max + 1, step):
        sc = score_fn(i)
        if np.isfinite(sc):
            scores[i] = sc
    n_valid = len(scores)
    print(f"[{label}] 유효 후보 {n_valid}개 (워밍업≥{ctx.i_min})")
    return StageScores(raw=scores, ranks=assign_ranks(scores, higher_is_better))


def dtw_z_on_segment(target_z: np.ndarray, hist: np.ndarray) -> float:
    if not segment_finite(hist, target_z.size):
        return float("nan")
    hist_z = safe_zscore(hist)
    if not np.all(np.isfinite(hist_z)):
        return float("nan")
    return float(dtw_distance(target_z, hist_z))


def run_price_zscore_pearson(ctx: RunContext) -> StageScores:
    target = ctx.target_price_z

    def score_at(i: int) -> float:
        seg = ctx.values_price[i : i + ctx.obs]
        if not segment_finite(seg, ctx.obs):
            return float("nan")
        return pearson_raw(target, safe_zscore(seg))

    return scan_similarity(ctx, score_at, "1-1 주가 z-score · Pearson", True)


def run_price_zscore_dtw(ctx: RunContext) -> StageScores:
    target = ctx.target_price_z

    def score_at(i: int) -> float:
        seg = ctx.values_price[i : i + ctx.obs]
        return dtw_z_on_segment(target, seg)

    return scan_similarity(ctx, score_at, "1-2 주가 z-score · DTW", False)


def run_log_pearson(ctx: RunContext) -> StageScores:
    target = ctx.target_log_raw

    def score_at(i: int) -> float:
        seg = ctx.values_log[i : i + ctx.obs]
        if not segment_finite(seg, ctx.obs):
            return float("nan")
        return pearson_raw(target, seg)

    return scan_similarity(ctx, score_at, "2-1 로그수익률 · Pearson", True)


def run_log_zscore_dtw(ctx: RunContext) -> StageScores:
    target = ctx.target_log_z

    def score_at(i: int) -> float:
        seg = ctx.values_log[i : i + ctx.obs]
        return dtw_z_on_segment(target, seg)

    return scan_similarity(ctx, score_at, "2-2 로그수익률 z-score · DTW", False)


def _ma_track_label(ctx: RunContext, base: str) -> str:
    return f"{base} [MA={ctx.ma_windows_label}]"


def run_ma_zscore_pearson(ctx: RunContext) -> StageScores:
    def score_at(i: int) -> float:
        best = float("nan")
        for w in ctx.ma_windows:
            seg = ctx.ma_series[w][i : i + ctx.obs]
            if not segment_finite(seg, ctx.obs):
                continue
            pr = pearson_raw(ctx.target_ma_z[w], safe_zscore(seg))
            if np.isfinite(pr):
                best = pr if not np.isfinite(best) else max(best, pr)
        return best

    return scan_similarity(
        ctx,
        score_at,
        _ma_track_label(ctx, "3-1 주가 MA z-score · Pearson"),
        True,
    )


def run_ma_zscore_dtw(ctx: RunContext) -> StageScores:
    def score_at(i: int) -> float:
        best = float("inf")
        for w in ctx.ma_windows:
            seg = ctx.ma_series[w][i : i + ctx.obs]
            d = dtw_z_on_segment(ctx.target_ma_z[w], seg)
            if np.isfinite(d):
                best = min(best, d)
        return best if best < float("inf") else float("nan")

    return scan_similarity(
        ctx,
        score_at,
        _ma_track_label(ctx, "3-2 주가 MA z-score · DTW"),
        False,
    )


TRACK_RUNNERS: dict[str, Callable[[RunContext], StageScores]] = {
    "price_zscore_pearson": run_price_zscore_pearson,
    "price_zscore_dtw": run_price_zscore_dtw,
    "log_pearson": run_log_pearson,
    "log_zscore_dtw": run_log_zscore_dtw,
    "ma_zscore_pearson": run_ma_zscore_pearson,
    "ma_zscore_dtw": run_ma_zscore_dtw,
}


def run_pipeline(
    ctx: RunContext,
    pipe: PipelineConfig,
) -> PipelineOutcome | None:
    tracks: dict[str, StageScores] = {}
    for spec in TRACK_SPECS:
        if not is_track_enabled(pipe, spec.key):
            print(f"[건너뜀] {spec.label} — tracks.{spec.key}: false")
            continue
        if spec.needs_dtw and not ctx.use_dtw:
            print(
                f"[건너뜀] {spec.label} — DTW 비활성 "
                "(dtaidistance/fastdtw 미설치 또는 use_dtw=false)"
            )
            continue
        if spec.key.startswith("ma_zscore") and not ctx.ma_windows:
            print(f"[건너뜀] {spec.label} — 유효한 ma_windows 없음")
            continue
        tracks[spec.key] = TRACK_RUNNERS[spec.key](ctx)

    if not tracks:
        return None
    return PipelineOutcome(tracks=tracks)


def build_target_summary(
    ctx: RunContext,
    pipe: PipelineConfig,
) -> tuple[list[str], str, str]:
    """콘솔·txt·md용 타겟 구간 요약."""
    ws = ctx.ws
    te = ws.target_end_idx
    ts = ws.target_start_idx
    last_sim = ws.target_start_idx - ctx.obs
    target_ret = pattern_return_pct(ctx.close.iloc[ws.target_slice])
    enabled = [
        spec.label for spec in TRACK_SPECS if is_track_enabled(pipe, spec.key)
    ]
    lines = [
        "=== 타겟 구간 ===",
        (
            f"티커: {ctx.ticker} | 타겟: "
            f"{ctx.close.index[ts].strftime('%Y-%m-%d')} ~ "
            f"{ctx.close.index[te].strftime('%Y-%m-%d')} | 관찰 {ctx.obs}거래일"
        ),
        f"타겟 구간 수익률(종가): {target_ret:.4f} %",
        f"미래 관찰: {ctx.forward_days}거래일",
        f"활성 트랙: {', '.join(enabled) if enabled else '(없음)'}",
        f"워밍업: 후보 시작 인덱스 ≥ {ctx.i_min}",
    ]
    if ctx.ma_windows:
        lines.insert(-1, f"MA 창(3번): [{ctx.ma_windows_label}]")
    if ctx.scan_desc.strip():
        lines.append(ctx.scan_desc)
    if last_sim >= 0:
        lines.append(
            f"유사 구간 마지막 가능 시작일: "
            f"{ctx.close.index[last_sim].strftime('%Y-%m-%d')}"
        )

    md_rows = [
        "| 항목 | 값 |",
        "| --- | --- |",
        f"| 티커 | {ctx.ticker} |",
        (
            f"| 타겟 구간 | "
            f"{ctx.close.index[ts].strftime('%Y-%m-%d')} ~ "
            f"{ctx.close.index[te].strftime('%Y-%m-%d')} ({ctx.obs}거래일) |"
        ),
        f"| 타겟 수익률 | {target_ret:.4f} % |",
        f"| 미래 관찰 | {ctx.forward_days}거래일 |",
        f"| 활성 트랙 | {len(enabled)}개 |",
    ]
    if ctx.ma_windows:
        md_rows.append(f"| MA 창 | {ctx.ma_windows_label} |")
    md_block = "## 타겟 구간\n\n" + "\n".join(md_rows) + "\n"
    txt_block = "\n".join(lines)
    return lines, txt_block, md_block


def _print_target_header(ctx: RunContext, pipe: PipelineConfig) -> None:
    lines, _, _ = build_target_summary(ctx, pipe)
    print("\n" + "\n".join(lines) + "\n")


def build_display_rows(
    close: pd.Series,
    values: np.ndarray,
    ranked_is: list[int],
    score_by_i: dict[int, float],
    forward_days: int,
    obs: int,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for rank, i in enumerate(ranked_is, start=1):
        sim_slice = close.iloc[i : i + obs]
        raw_score = score_by_i.get(i, float("nan"))
        end_idx = i + obs - 1
        fr = forward_return_pct(values, end_idx, forward_days)
        win_ret = pattern_return_pct(sim_slice)
        out.append(
            {
                "순위": rank,
                "시작일": sim_slice.index[0].strftime("%Y-%m-%d"),
                "종료일": sim_slice.index[-1].strftime("%Y-%m-%d"),
                "스코어": float(raw_score) if np.isfinite(raw_score) else float("nan"),
                "유사구간수익률": float(win_ret) if np.isfinite(win_ret) else float("nan"),
                "미래수익률": float(fr) if np.isfinite(fr) else float("nan"),
            }
        )
    return out


def top_ranked(st: StageScores, top_n: int, higher_is_better: bool) -> list[int]:
    if not st.raw:
        return []
    return sorted(st.raw, key=lambda i: st.raw[i], reverse=higher_is_better)[:top_n]


def _score_legend_label(
    rank: int,
    start_date: str,
    score: float,
    higher_is_better: bool,
) -> str:
    if not np.isfinite(score):
        return f"#{rank} {start_date}"
    if higher_is_better:
        return f"#{rank} {start_date}  r={score:.3f}"
    return f"#{rank} {start_date}  d={score:.3f}"


def plot_overlay_enhanced(
    close: pd.Series,
    values: np.ndarray,
    ws: WindowSpec,
    ranked_is: list[int],
    scores_by_i: dict[int, float],
    method: str,
    forward_days: int,
    out_path: Path,
    higher_is_better: bool = True,
) -> None:
    """시인성 개선: 순위·스코어 범례, 1위 강조, 구간 라벨, 메타 박스."""
    obs = ws.obs
    n = len(values)
    ts, te = ws.target_start_idx, ws.target_end_idx
    target_date_str = close.index[te].strftime("%Y-%m-%d")
    target_ret = pattern_return_pct(close.iloc[ws.target_slice])

    t_seg = slice_extended(values, ts, obs, forward_days, n)
    y_t = safe_minmax(t_seg)
    x_t = np.arange(len(y_t))
    obs_end = obs - 1

    fig, ax = plt.subplots(figsize=(14, 8))
    fig.patch.set_facecolor("#FAFAFA")
    ax.set_facecolor("#FFFFFF")

    max_len = len(y_t)
    for k, i in enumerate(ranked_is):
        seg = slice_extended(values, i, obs, forward_days, n)
        y = safe_minmax(seg)
        x = np.arange(len(y))
        max_len = max(max_len, len(y))
        date_s = close.index[i].strftime("%Y-%m-%d")
        lbl = _score_legend_label(k + 1, date_s, scores_by_i.get(i, float("nan")), higher_is_better)
        ci = min(k, len(RANK_COLORS) - 1)
        ax.plot(
            x,
            y,
            color=RANK_COLORS[ci],
            lw=RANK_LINEWIDTHS[ci],
            alpha=RANK_ALPHAS[ci],
            label=lbl,
            zorder=5 + k,
        )

    ax.plot(
        x_t[: obs_end + 1],
        y_t[: obs_end + 1],
        color="#111111",
        lw=3.2,
        label="Target (관찰)",
        zorder=20,
    )
    if len(y_t) > obs:
        ax.plot(
            x_t[obs_end:],
            y_t[obs_end:],
            color="#111111",
            lw=2.0,
            ls=":",
            alpha=0.45,
            label="Target (미래·미정)",
            zorder=19,
        )

    x_right = max_len - 1
    ax.axvline(obs_end, color="#DC2626", ls="--", lw=2.0, alpha=0.9, zorder=8)
    ax.annotate(
        "관찰 끝",
        xy=(obs_end, 1.02),
        xycoords=("data", "axes fraction"),
        ha="center",
        fontsize=10,
        color="#DC2626",
        fontweight="bold",
    )
    if max_len > obs:
        ax.axvspan(obs_end, x_right, alpha=0.12, color="#D97706", zorder=0)
        ax.text(
            obs_end + (x_right - obs_end) * 0.5,
            0.04,
            f"미래 관찰 +{forward_days}거래일",
            transform=ax.get_xaxis_transform(),
            ha="center",
            fontsize=10,
            color="#92400E",
            bbox=dict(boxstyle="round,pad=0.3", fc="#FEF3C7", ec="#D97706", alpha=0.9),
        )

    info = (
        f"{close.name or '—'}  |  타겟 {target_date_str}\n"
        f"관찰 {obs}일 + 미래 {forward_days}일  |  "
        f"타겟 수익률 {target_ret:+.2f}%\n"
        f"Y축: 구간별 min-max (0~1) — 절대 수익률 크기는 반영 안 됨"
    )
    ax.text(
        0.02,
        0.98,
        info,
        transform=ax.transAxes,
        va="top",
        ha="left",
        fontsize=9,
        bbox=dict(boxstyle="round,pad=0.45", fc="white", ec="#CBD5E1", alpha=0.95),
    )

    ax.set_title(
        f"유사 패턴 비교 · 개선형 (타겟: {target_date_str})\n[{method}]",
        fontsize=14,
        fontweight="bold",
        pad=12,
    )
    ax.set_xlabel("거래일 (Day 0 = 구간 시작)", fontsize=11)
    ax.set_ylabel("Min-Max 정규화 종가", fontsize=11)
    ax.set_xticks(list(range(0, max(obs + forward_days, max_len) + 1, 20)))
    ax.grid(True, alpha=0.25, linestyle="-", linewidth=0.6)
    x_hi = max(float(x_right) + 0.5, float(obs + forward_days - 1) + 0.5)
    ax.set_xlim(-0.5, x_hi)
    ax.set_ylim(-0.03, 1.06)
    ax.legend(
        loc="upper center",
        bbox_to_anchor=(0.5, -0.11),
        ncol=3,
        fontsize=9,
        frameon=True,
        fancybox=True,
    )
    fig.tight_layout()
    fig.savefig(out_path, dpi=200, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)


def emit_track_results(
    ctx: RunContext,
    outcome: PipelineOutcome,
    report_txt: list[str],
    report_md: list[str],
) -> None:
    price_vals = ctx.close.values.astype(float)
    notes = METHODOLOGY_NOTES.strip().replace("{ma_w}", ctx.ma_windows_label or "-")
    print(notes)
    print()

    for spec in TRACK_SPECS:
        st = outcome.tracks.get(spec.key)
        if st is None:
            continue
        label = (
            _ma_track_label(ctx, spec.label)
            if spec.key.startswith("ma_zscore")
            else spec.label
        )
        ranked = top_ranked(st, ctx.top_n, spec.higher_is_better)
        if not ranked:
            print(f"\n=== {label} ===\n유효한 후보 없음.\n")
            continue

        recs = build_display_rows(
            ctx.close,
            price_vals,
            ranked,
            st.raw,
            ctx.forward_days,
            ctx.obs,
        )
        cols = ["순위", "시작일", "종료일", "스코어", "유사구간수익률", "미래수익률"]
        dfm = pd.DataFrame(recs)[cols]
        header = f"=== {label} ==="
        tbl = format_dataframe_table(dfm)
        sec = f"\n{header}\n{tbl}\n"
        print(sec)
        report_txt.append(sec.strip())
        note = ""
        if not spec.higher_is_better:
            note = "\n\n> **DTW:** z-score **거리**(작을수록 유사).\n"
            report_txt[-1] += "\n[안내] DTW 거리 — 작을수록 유사."
        report_md.append(f"## {label}\n\n{dataframe_to_markdown(dfm)}{note}\n")

        if ctx.save_csv:
            p = ctx.out_dir / f"table_{spec.slug}_{ctx.date_tag}.csv"
            dfm.to_csv(p, index=False, encoding="utf-8-sig")
            print(f"표 CSV 저장: {p}")

        png = ctx.out_dir / f"{ctx.chart_prefix}_{spec.slug}_{ctx.date_tag}.png"
        plot_overlay_enhanced(
            ctx.close,
            price_vals,
            ctx.ws,
            ranked,
            st.raw,
            label,
            ctx.forward_days,
            png,
            higher_is_better=spec.higher_is_better,
        )
        print(f"차트: {png}")


def write_result_documents(
    ctx: RunContext,
    pipe: PipelineConfig,
    outcome: PipelineOutcome,
) -> None:
    """표·TXT·MD 결과문서 저장 (main 과 동일)."""
    report_txt: list[str] = []
    _, target_txt, target_md = build_target_summary(ctx, pipe)
    notes = METHODOLOGY_NOTES.strip().replace("{ma_w}", ctx.ma_windows_label or "-")
    report_txt.append(target_txt)
    report_md: list[str] = [
        "# dejavu 유사 패턴 분석\n\n",
        target_md + "\n",
        "## 방법론\n\n```\n" + notes + "\n```\n\n",
        "## 트랙별 결과\n\n",
    ]
    if pipe.emit_tracks:
        emit_track_results(ctx, outcome, report_txt, report_md)
    if ctx.save_txt and report_txt:
        p = ctx.out_dir / f"results_tables_dejavu_{ctx.date_tag}.txt"
        body = notes + "\n\n" + "\n\n".join(report_txt)
        p.write_text("\ufeff" + body, encoding="utf-8")
        print(f"표 텍스트 저장: {p}")
    if ctx.save_md and report_md:
        p = ctx.out_dir / f"results_tables_dejavu_{ctx.date_tag}.md"
        p.write_text("\n\n".join(report_md), encoding="utf-8")
        print(f"표 Markdown 저장: {p}")
    elif not ctx.save_md and report_md:
        print(
            "알림: save_table_md=false — 통합 Markdown 미저장. "
            "dejavu.yml 에서 save_table_md: true 로 설정하세요."
        )


def run_pipeline_disabled() -> None:
    print("오류: pipeline_dejavu.enabled=false — dejavu 파이프라인이 비활성화되었습니다.")
    print("dejavu.yml 에서 pipeline_dejavu.enabled: true 로 설정하세요.")
    raise SystemExit(1)


def _format_elapsed(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.1f}초"
    minutes = int(seconds // 60)
    remainder = seconds % 60
    return f"{minutes}분 {remainder:.1f}초"


def main(argv: list[str] | None = None) -> None:
    argv = argv or sys.argv[1:]
    cfg_path = Path(argv[0]) if argv else None
    raw = load_dejavu_config(cfg_path)
    configure_stdio_utf8()

    pipe = parse_pipeline_config(raw)
    if not pipe.enabled:
        run_pipeline_disabled()
        return

    started_at = time.perf_counter()
    ctx = build_run_context(raw, pipe)
    _print_target_header(ctx, pipe)

    outcome = run_pipeline(ctx, pipe)
    if outcome is None:
        print("오류: 활성 트랙 없음 — pipeline_dejavu.tracks 확인")
        raise SystemExit(1)

    write_result_documents(ctx, pipe, outcome)
    print(f"\n소요 시간: {_format_elapsed(time.perf_counter() - started_at)}")


if __name__ == "__main__":
    main()
