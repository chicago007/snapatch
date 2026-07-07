"""snapatch — Streamlit 웹 대시보드 진입점.

실행 (프로젝트 루트):
    python -m streamlit run hub/ui/maingate.py
    python run.py  → [1] 웹 UI

다크 트레이딩 터미널 스타일 대시보드 (라이트/다크 토글).
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import csv
import importlib
import os
from datetime import datetime, timedelta, timezone

import streamlit as st

from hub import bootstrap

bootstrap.init()

from hub import project_info as _project_info

importlib.reload(_project_info)

AUTHOR_EMAIL = _project_info.AUTHOR_EMAIL
AUTHOR_NAME = _project_info.AUTHOR_NAME
GITHUB_URL = _project_info.GITHUB_URL
VERSION_LABEL = _project_info.VERSION_LABEL

from hub.paths import breaker_output_dir, project_root

st.set_page_config(
    page_title="snapatch",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

KST = timezone(timedelta(hours=9))

# ----- 아이콘 (feather 스타일 인라인 SVG) -----
_ICONS = {
    "logo": '<polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/>',
    "home": (
        '<path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>'
        '<polyline points="9 22 9 12 15 12 15 22"/>'
    ),
    "zap": '<polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/>',
    "search": (
        '<circle cx="11" cy="11" r="8"/>'
        '<line x1="21" y1="21" x2="16.65" y2="16.65"/>'
    ),
    "clock": (
        '<circle cx="12" cy="12" r="10"/>'
        '<polyline points="12 6 12 12 16 14"/>'
    ),
    "dna": (
        '<path d="M7 3c0 3 10 5 10 9s-10 6-10 9"/>'
        '<path d="M17 3c0 3-10 5-10 9s10 6 10 9"/>'
        '<line x1="8.5" y1="6" x2="15.5" y2="6"/>'
        '<line x1="9" y1="9.5" x2="15" y2="9.5"/>'
        '<line x1="9" y1="14.5" x2="15" y2="14.5"/>'
        '<line x1="8.5" y1="18" x2="15.5" y2="18"/>'
    ),
    "save": (
        '<path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/>'
        '<polyline points="17 21 17 13 7 13 7 21"/>'
        '<polyline points="7 3 7 8 15 8"/>'
    ),
    "users": (
        '<path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/>'
        '<circle cx="9" cy="7" r="4"/>'
        '<path d="M23 21v-2a4 4 0 0 0-3-3.87"/>'
        '<path d="M16 3.13a4 4 0 0 1 0 7.75"/>'
    ),
    "trending": (
        '<polyline points="23 6 13.5 15.5 8.5 10.5 1 18"/>'
        '<polyline points="17 6 23 6 23 12"/>'
    ),
    "moon": '<path d="M21 12.8A9 9 0 1 1 11.2 3 7 7 0 0 0 21 12.8z"/>',
    "book": (
        '<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/>'
        '<path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/>'
    ),
    "sun": (
        '<circle cx="12" cy="12" r="5"/>'
        '<line x1="12" y1="1" x2="12" y2="3"/>'
        '<line x1="12" y1="21" x2="12" y2="23"/>'
        '<line x1="4.2" y1="4.2" x2="5.6" y2="5.6"/>'
        '<line x1="18.4" y1="18.4" x2="19.8" y2="19.8"/>'
        '<line x1="1" y1="12" x2="3" y2="12"/>'
        '<line x1="21" y1="12" x2="23" y2="12"/>'
        '<line x1="4.2" y1="19.8" x2="5.6" y2="18.4"/>'
        '<line x1="18.4" y1="5.6" x2="19.8" y2="4.2"/>'
    ),
}


def _svg(name: str, size: int = 22) -> str:
    return (
        f'<svg viewBox="0 0 24 24" width="{size}" height="{size}" fill="none" '
        'stroke="currentColor" stroke-width="2" stroke-linecap="round" '
        f'stroke-linejoin="round">{_ICONS[name]}</svg>'
    )


_FEATURES = {
    "breaker": {
        "icon": "zap",
        "title": "시황 속보",
        "desc": "실시간 시장 이슈와 주요 테마를 빠르게 포착해 전달합니다.",
        "accent": "#3b82f6",
    },
    "diver": {
        "icon": "search",
        "title": "키워드 뉴스 분석",
        "desc": "뉴스 데이터를 키워드 기반으로 분석하여 시장의 흐름을 인사이트로 연결합니다.",
        "accent": "#f59e0b",
    },
    "dejavu": {
        "icon": "clock",
        "title": "과거 유사 패턴",
        "desc": "과거 시장의 유사한 패턴을 찾아 현재와 비교 분석합니다.",
        "accent": "#14b8a6",
    },
    "match": {
        "icon": "dna",
        "title": "유사 종목 검색",
        "desc": "종목의 재무·수급·변동성 등 다양한 지표 기반으로 유사 종목을 찾아냅니다.",
        "accent": "#22c55e",
    },
}

# 기능 카드용 미니 차트 장식
_MINI_BREAKER = (
    '<svg class="snap-mini" width="150" height="68" viewBox="0 0 150 68" fill="none">'
    '<polyline points="2,56 24,44 46,50 70,28 92,34 116,14 148,6" '
    'stroke="#3b82f6" stroke-width="3" stroke-linecap="round" '
    'stroke-linejoin="round"/></svg>'
)
_MINI_DEJAVU = (
    '<svg class="snap-mini" width="160" height="72" viewBox="0 0 160 72" '
    'fill="none" stroke="#2dd4bf" stroke-width="2">'
    '<line x1="14" y1="18" x2="14" y2="56"/>'
    '<rect x="9" y="30" width="10" height="16" fill="#0f766e"/>'
    '<line x1="38" y1="14" x2="38" y2="50"/>'
    '<rect x="33" y="22" width="10" height="20" fill="#0f766e"/>'
    '<line x1="62" y1="22" x2="62" y2="58"/>'
    '<rect x="57" y="34" width="10" height="14" fill="#134e4a"/>'
    '<line x1="86" y1="16" x2="86" y2="46"/>'
    '<rect x="81" y="24" width="10" height="14" fill="#0f766e"/>'
    '<path d="M100 30 L122 18 L140 26 L156 12" stroke="#5eead4" '
    'stroke-width="2.5" stroke-dasharray="5 4"/></svg>'
)


def _palette_css(theme: str) -> str:
    if theme == "light":
        return """
:root{
  --bg:#eef2f8; --bg2:#f8fafc; --card:#ffffff; --card2:#ffffff;
  --border:#dbe3ef; --text:#0f172a; --muted:#64748b; --hover:#f1f5f9;
  --sidebar:#f5f8fd; --brand:#2563eb;
}
"""
    return """
:root{
  --bg:#0a0f1d; --bg2:#0d1428; --card:#111b30; --card2:#0f1a2e;
  --border:#1e2c45; --text:#f1f5f9; --muted:#94a3b8; --hover:#16223a;
  --sidebar:#0b1222; --brand:#3b82f6;
}
"""


_BASE_CSS = """
<style>
[data-testid="stAppViewContainer"], .stApp {background:var(--bg);}
[data-testid="stHeader"] {background:transparent;}
#MainMenu, footer {visibility:hidden;}
.block-container {padding-top:1.4rem; padding-bottom:2rem; max-width:1180px;}
section[data-testid="stSidebar"] > div {background:var(--sidebar); padding-top:.6rem;
  display:flex; flex-direction:column; min-height:100vh;}
.snap-sidebar-body {flex:1; display:flex; flex-direction:column; min-height:0;}
.snap-sidebar-spacer {flex:1; min-height:12px;}

/* ---- 사이드바 브랜드 ---- */
.snap-brand {display:flex; align-items:center; gap:11px; padding:6px 8px 16px;}
.snap-brand .b-chip {
  width:38px; height:38px; border-radius:11px; display:flex; align-items:center;
  justify-content:center; color:#fff;
  background:linear-gradient(135deg,#3b82f6,#22d3ee);
}
.snap-brand .b-name {font-size:1.45rem; font-weight:800; color:var(--text);
  letter-spacing:-.5px;}

/* ---- 사이드바 네비 ---- */
.snap-nav {display:flex; flex-direction:column; gap:5px;}
.snap-nav-bottom {display:flex; flex-direction:column; gap:5px; margin-top:18px;
  padding-top:14px; border-top:1px solid var(--border);}
.nav-item {
  display:flex; align-items:center; gap:11px; padding:9px 11px; border-radius:13px;
  text-decoration:none; border:1px solid transparent; transition:background .15s;
}
.nav-item:hover {background:var(--hover);}
.nav-item.active {
  background:color-mix(in srgb,var(--brand) 16%, transparent);
  border-color:color-mix(in srgb,var(--brand) 45%, transparent);
}
.nav-chip {
  width:34px; height:34px; border-radius:10px; flex:0 0 auto; display:flex;
  align-items:center; justify-content:center; color:var(--accent);
  background:color-mix(in srgb,var(--accent) 17%, transparent);
}
.nav-text {display:flex; flex-direction:column; line-height:1.18; flex:1; min-width:0;}
.nav-name {color:var(--text); font-weight:700; font-size:.92rem;}
.nav-sub {color:var(--muted); font-size:.72rem; white-space:nowrap; overflow:hidden;
  text-overflow:ellipsis;}
.nav-badge {font-size:.6rem; font-weight:800; padding:2px 8px; border-radius:999px;
  flex:0 0 auto;}
.nav-badge.on {background:rgba(34,197,94,.16); color:#4ade80;
  border:1px solid rgba(34,197,94,.45);}
.nav-badge.key {background:rgba(245,158,11,.16); color:#fbbf24;
  border:1px solid rgba(245,158,11,.45);}
.snap-foot {color:var(--muted); font-size:.72rem; padding:14px 8px 4px; line-height:1.5;}
.snap-foot a {color:var(--brand); text-decoration:none;}
.snap-foot a:hover {text-decoration:underline;}
.snap-disclaimer a {color:var(--brand); text-decoration:none;}
.snap-disclaimer a:hover {text-decoration:underline;}

/* ---- 상단바 ---- */
.snap-top {display:flex; align-items:center; justify-content:space-between;
  margin:2px 0 18px;}
.snap-top .t-title {font-size:2rem; font-weight:800; color:var(--text);
  letter-spacing:-1px; display:flex; align-items:center; gap:10px;}
.snap-top .t-version {font-size:.78rem; font-weight:700; color:var(--brand);
  background:color-mix(in srgb,var(--brand) 14%, transparent);
  border:1px solid color-mix(in srgb,var(--brand) 35%, transparent);
  padding:3px 9px; border-radius:999px; letter-spacing:.03em;}
.snap-top .t-right {display:flex; align-items:center; gap:16px;}
.snap-top .t-date {color:var(--muted); font-size:.86rem; font-weight:600;}
.theme-toggle {display:inline-flex; background:var(--card); border:1px solid var(--border);
  border-radius:999px; padding:3px;}
.theme-toggle a {display:flex; align-items:center; justify-content:center; width:32px;
  height:26px; border-radius:999px; color:var(--muted); text-decoration:none;}
.theme-toggle a.active {background:color-mix(in srgb,var(--brand) 90%, #fff);
  color:#fff;}

/* ---- KPI ---- */
.snap-kpi-row {display:grid; grid-template-columns:repeat(4,1fr); gap:16px;
  margin-bottom:22px;}
.snap-kpi {background:var(--card); border:1px solid var(--border); border-radius:16px;
  padding:16px 18px; display:flex; align-items:center; gap:14px;}
.snap-kpi .k-chip {width:46px; height:46px; border-radius:12px; flex:0 0 auto;
  display:flex; align-items:center; justify-content:center; color:var(--accent);
  background:color-mix(in srgb,var(--accent) 16%, transparent);}
.snap-kpi .k-label {color:var(--muted); font-size:.78rem; margin-bottom:3px;}
.snap-kpi .k-value {color:var(--text); font-size:1.65rem; font-weight:800;
  line-height:1; letter-spacing:-.5px;}

/* ---- 기능 카드 ---- */
.snap-card {
  position:relative; background:var(--card); border-radius:18px;
  border:1px solid color-mix(in srgb,var(--accent) 32%, var(--border));
  padding:22px 24px 22px; min-height:178px; overflow:hidden;
  transition:border-color .2s, box-shadow .2s;
}
.snap-card:hover {border-color:var(--accent);
  box-shadow:0 14px 36px -16px var(--accent);}
.snap-card .c-chip {
  width:56px; height:56px; border-radius:15px; display:inline-flex;
  align-items:center; justify-content:center; color:var(--accent);
  background:color-mix(in srgb,var(--accent) 16%, transparent);
}
.snap-card .c-name {font-size:1.55rem; font-weight:800; color:var(--text);
  margin:14px 0 0; letter-spacing:-.5px;}
.snap-card .c-title {color:var(--accent); font-weight:700; font-size:1rem;
  margin-top:1px;}
.snap-card .c-desc {color:var(--muted); font-size:.86rem; margin-top:10px;
  max-width:60%; line-height:1.55;}
.snap-card .open-btn {display:inline-flex; align-items:center; gap:6px;
  margin-top:16px; background:var(--brand); color:#fff; border:none;
  padding:8px 18px; border-radius:11px; font-weight:700; font-size:.85rem;
  text-decoration:none;}
.snap-card .open-btn:hover {filter:brightness(1.1);}
.snap-mini {position:absolute; right:22px; top:64px;}
.sim-badge {position:absolute; right:24px; top:46px;
  background:rgba(20,184,166,.16); color:#2dd4bf;
  border:1px solid rgba(20,184,166,.45); padding:3px 11px; border-radius:999px;
  font-size:.72rem; font-weight:700;}
.snap-disclaimer {color:var(--muted); font-size:.78rem; margin-top:24px;
  padding-top:16px; border-top:1px solid var(--border);}
</style>
"""


def _feature_status() -> dict[str, bool]:
    """기능별 즉시 실행 가능 여부 (필수 키 충족 여부)."""
    has_gemini = bool(
        os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    )
    has_naver = bool(
        os.getenv("NAVER_CLIENT_ID") and os.getenv("NAVER_CLIENT_SECRET")
    )
    use_vertex = os.getenv("GOOGLE_GENAI_USE_VERTEXAI", "").lower() in (
        "true",
        "1",
        "yes",
    )
    if use_vertex:
        has_diver_ai = bool(os.getenv("GOOGLE_CLOUD_PROJECT"))
    else:
        has_diver_ai = has_gemini
    return {
        "breaker": has_gemini,
        "diver": has_naver and has_diver_ai,
        "dejavu": True,
        "match": True,
    }


def _report_stats() -> tuple[str, int, int]:
    """(마지막 리포트 시각 HH:MM, 전체 리포트 수, 오늘 생성 수)."""
    reports_dir = breaker_output_dir()
    if not reports_dir.is_dir():
        legacy_root = project_root() / "reports"
        reports_dir = legacy_root if legacy_root.is_dir() else None
    if reports_dir is None or not reports_dir.is_dir():
        return "—", 0, 0
    files = sorted(
        reports_dir.glob("*.md"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not files:
        return "—", 0, 0
    last_time = datetime.fromtimestamp(files[0].stat().st_mtime).strftime("%H:%M")
    today = datetime.now().date()
    today_count = sum(
        1
        for p in files
        if datetime.fromtimestamp(p.stat().st_mtime).date() == today
    )
    return last_time, len(files), today_count


def _ticker_count() -> int:
    csv_path = bootstrap.engines_root() / "match" / "uni.csv"
    if not csv_path.is_file():
        return 0
    try:
        with csv_path.open(encoding="utf-8") as fp:
            return max(0, sum(1 for _ in csv.reader(fp)) - 1)
    except OSError:
        return 0


def _href(page: str, theme: str) -> str:
    return f"?page={page}&theme={theme}"


def _render_topbar(page: str, theme: str) -> None:
    now = datetime.now(KST).strftime("%Y-%m-%d %H:%M KST")
    dark_cls = "active" if theme == "dark" else ""
    light_cls = "active" if theme == "light" else ""
    toggle = (
        '<div class="theme-toggle">'
        f'<a class="{dark_cls}" target="_self" href="{_href(page, "dark")}" '
        f'title="다크">{_svg("moon", 15)}</a>'
        f'<a class="{light_cls}" target="_self" href="{_href(page, "light")}" '
        f'title="라이트">{_svg("sun", 15)}</a>'
        '</div>'
    )
    st.markdown(
        f'<div class="snap-top"><div class="t-title">snapatch'
        f'<span class="t-version">{VERSION_LABEL}</span></div>'
        f'<div class="t-right">{toggle}'
        f'<span class="t-date">{now}</span></div></div>',
        unsafe_allow_html=True,
    )


def _render_kpis() -> None:
    last_report, report_count, today_count = _report_stats()
    tickers = _ticker_count()
    tiles = [
        ("clock", "마지막 리포트", last_report or "—", "#3b82f6"),
        ("save", "저장 리포트", f"{report_count}", "#a855f7"),
        ("users", "후보 종목", f"{tickers}", "#06b6d4"),
        ("trending", "오늘 분석", f"{today_count}", "#22c55e"),
    ]
    cells = "".join(
        f'<div class="snap-kpi" style="--accent:{accent}">'
        f'<span class="k-chip">{_svg(icon, 22)}</span>'
        f'<div><div class="k-label">{label}</div>'
        f'<div class="k-value">{value}</div></div></div>'
        for icon, label, value, accent in tiles
    )
    st.markdown(
        f'<div class="snap-kpi-row">{cells}</div>',
        unsafe_allow_html=True,
    )


def _feature_card_html(key: str, theme: str) -> str:
    meta = _FEATURES[key]
    extra = ""
    if key == "breaker":
        extra = _MINI_BREAKER
    elif key == "dejavu":
        extra = '<span class="sim-badge">유사도 87%</span>' + _MINI_DEJAVU
    return (
        f'<div class="snap-card" style="--accent:{meta["accent"]}">'
        f'<span class="c-chip">{_svg(meta["icon"], 26)}</span>'
        f'{extra}'
        f'<div class="c-name">{key}</div>'
        f'<div class="c-title">{meta["title"]}</div>'
        f'<div class="c-desc">{meta["desc"]}</div>'
        f'<a class="open-btn" target="_self" href="{_href(key, theme)}">열기 →</a>'
        '</div>'
    )


def _render_home(theme: str) -> None:
    _render_kpis()
    keys = list(_FEATURES.keys())
    for row_start in (0, 2):
        cols = st.columns(2, gap="medium")
        for offset in (0, 1):
            key = keys[row_start + offset]
            with cols[offset]:
                st.markdown(
                    _feature_card_html(key, theme),
                    unsafe_allow_html=True,
                )
    st.markdown(
        f'<div class="snap-disclaimer">© 2026 snapatch · '
        f'<a href="{GITHUB_URL}" target="_blank" rel="noopener">GitHub</a> · '
        f'{AUTHOR_NAME}<br>'
        'AI·시세 정보는 참고용이며 투자 판단·손익 책임은 이용자 본인에게 있습니다.</div>',
        unsafe_allow_html=True,
    )
    with st.expander("About snapatch", expanded=False):
        st.markdown(
            f"**{VERSION_LABEL}** · **{AUTHOR_NAME}**  \n"
            f"[GitHub]({GITHUB_URL}) · "
            f"[{AUTHOR_EMAIL}](mailto:{AUTHOR_EMAIL}) · "
            f"[Changelog]({GITHUB_URL}/blob/main/CHANGELOG.md) · "
            f"[사용 설명서]({_href('guide', theme)})  \n\n"
            "주식 속보 · AI 뉴스 분석 · 과거 패턴 · 유사 종목을 "
            "하나의 대시보드에서 사용할 수 있는 통합 플랫폼입니다."
        )


def _render_sidebar(page: str, theme: str) -> None:
    status = _feature_status()
    with st.sidebar:
        st.markdown(
            '<div class="snap-brand">'
            f'<span class="b-chip">{_svg("logo", 22)}</span>'
            '<span class="b-name">snapatch</span></div>',
            unsafe_allow_html=True,
        )
        main_items = [
            (
                f'<a class="nav-item {"active" if page == "home" else ""}" '
                f'target="_self" style="--accent:{"#3b82f6"}" '
                f'href="{_href("home", theme)}">'
                f'<span class="nav-chip">{_svg("home", 18)}</span>'
                '<span class="nav-text"><span class="nav-name">홈</span>'
                '<span class="nav-sub">대시보드</span></span></a>'
            )
        ]
        for key, meta in _FEATURES.items():
            active = "active" if page == key else ""
            badge_cls, badge_txt = (
                ("on", "ON") if status[key] else ("key", "KEY")
            )
            main_items.append(
                f'<a class="nav-item {active}" target="_self" '
                f'style="--accent:{meta["accent"]}" href="{_href(key, theme)}">'
                f'<span class="nav-chip">{_svg(meta["icon"], 18)}</span>'
                '<span class="nav-text">'
                f'<span class="nav-name">{key}</span>'
                f'<span class="nav-sub">{meta["title"]}</span></span>'
                f'<span class="nav-badge {badge_cls}">{badge_txt}</span></a>'
            )
        guide_item = (
            f'<a class="nav-item {"active" if page == "guide" else ""}" '
            f'target="_self" style="--accent:{"#8b5cf6"}" '
            f'href="{_href("guide", theme)}">'
            f'<span class="nav-chip">{_svg("book", 18)}</span>'
            '<span class="nav-text"><span class="nav-name">사용 설명서</span>'
            '<span class="nav-sub">웹 이용 · 다운로드 안내</span></span></a>'
        )
        st.markdown(
            '<div class="snap-sidebar-body">'
            f'<div class="snap-nav">{"".join(main_items)}</div>'
            '<div class="snap-sidebar-spacer"></div>'
            f'<div class="snap-nav-bottom">{guide_item}</div>'
            '</div>',
            unsafe_allow_html=True,
        )
        st.markdown(
            f'<div class="snap-foot">{VERSION_LABEL} · breaker · diver · dejavu · match<br>'
            f'<a href="{GITHUB_URL}" target="_blank" rel="noopener">GitHub</a> · '
            f'{AUTHOR_NAME}</div>',
            unsafe_allow_html=True,
        )


def main() -> None:
    page = st.query_params.get("page", "home")
    theme = st.query_params.get("theme", "dark")
    if page not in {"home", "guide", *_FEATURES}:
        page = "home"

    st.markdown(
        f"<style>{_palette_css(theme)}</style>{_BASE_CSS}",
        unsafe_allow_html=True,
    )
    _render_sidebar(page, theme)
    _render_topbar(page, theme)

    if page == "home":
        _render_home(theme)
        return

    if page == "guide":
        from hub.features import guide

        guide.render()
        return

    if page == "breaker":
        from hub.features import breaker

        breaker.render()
    elif page == "diver":
        from hub.features import diver

        diver.render()
    elif page == "dejavu":
        from hub.features import dejavu

        dejavu.render()
    elif page == "match":
        from hub.features import match

        match.render()


if __name__ == "__main__":
    main()
