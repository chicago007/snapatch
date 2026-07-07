"""breaker용 실시간 시세 조회 — 네이버금융(국내) · pykrx · Yahoo Finance.

국내 지수(코스피·코스닥): 네이버 금융 실시간 → pykrx(KRX) → Yahoo (^KS11, ^KQ11)
해외 지수·환율·원자재: Yahoo Finance chart API (requests, 별도 패키지 불필요)
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import requests

KST = timezone(timedelta(hours=9))
logger = logging.getLogger(__name__)
logging.getLogger("pykrx").setLevel(logging.CRITICAL)

_YAHOO_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; snapatch-breaker/1.0; +https://github.com/chicago007/snapatch)"
    ),
}
_NAVER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Referer": "https://finance.naver.com/sise/sise_index.naver",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8",
}
_YAHOO_CHART_URLS = (
    "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
    "https://query2.finance.yahoo.com/v8/finance/chart/{symbol}",
)
_NAVER_INDEX_URL = (
    "https://polling.finance.naver.com/api/realtime/domestic/index/{code}"
)

# pykrx 지수 티커 (1001=코스피, 2001=코스닥)
_PYKRX_INDICES: dict[str, str] = {
    "코스피": "1001",
    "코스닥": "2001",
}

# 네이버 금융 실시간 지수 코드
_NAVER_INDEX_CODES: dict[str, str] = {
    "코스피": "KOSPI",
    "코스닥": "KOSDAQ",
}

# Yahoo 심볼 (국내는 pykrx 실패 시 fallback)
_YAHOO_SYMBOLS: dict[str, str] = {
    "코스피": "^KS11",
    "코스닥": "^KQ11",
    "S&P500": "^GSPC",
    "나스닥": "^IXIC",
    "닛케이225": "^N225",
    "USD/KRW": "KRW=X",
    "WTI": "CL=F",
    "금": "GC=F",
    "은": "SI=F",
}


@dataclass(frozen=True)
class MarketQuote:
    name: str
    price: float | None
    change: float | None
    change_pct: float | None
    currency: str
    source: str
    as_of: str
    market_state: str | None = None


@dataclass
class MarketSnapshot:
    fetched_at: str
    quotes: list[MarketQuote] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def quote_by_name(self, name: str) -> MarketQuote | None:
        for quote in self.quotes:
            if quote.name == name:
                return quote
        return None


def _pct_change(current: float, previous: float) -> float:
    if previous == 0:
        return 0.0
    return (current - previous) / previous * 100.0


def _parse_number(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    cleaned = str(value).replace(",", "").strip()
    if not cleaned or cleaned == "-":
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _has_krx_credentials() -> bool:
    return bool(os.getenv("KRX_ID", "").strip() and os.getenv("KRX_PW", "").strip())


def _fetch_naver_index(name: str, code: str) -> MarketQuote | None:
    last_error: Exception | None = None
    for _attempt in range(2):
        try:
            resp = requests.get(
                _NAVER_INDEX_URL.format(code=code),
                headers=_NAVER_HEADERS,
                timeout=12,
            )
            resp.raise_for_status()
            payload = resp.json()
            rows = payload.get("datas") or []
            if not rows:
                continue
            row: dict[str, Any] = rows[0]
            break
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            continue
    else:
        logger.debug("naver %s failed: %s", name, last_error)
        return None

    price = _parse_number(row.get("closePrice"))
    if price is None or price <= 0:
        return None

    change = _parse_number(row.get("compareToPreviousClosePrice"))
    change_pct = _parse_number(row.get("fluctuationsRatio"))
    if change is None and change_pct is not None:
        prev = price / (1 + change_pct / 100.0) if change_pct != -100 else price
        change = price - prev
    if change_pct is None and change is not None:
        prev = price - change
        change_pct = _pct_change(price, prev) if prev else 0.0

    market_state = str(row.get("marketStatus") or "").upper() or None
    traded_at = row.get("localTradedAt")
    as_of = "네이버금융"
    if traded_at:
        try:
            dt = datetime.fromisoformat(str(traded_at))
            as_of = f"{dt.strftime('%Y-%m-%d %H:%M')} KST (네이버금융)"
        except ValueError:
            as_of = f"{traded_at} (네이버금융)"

    return MarketQuote(
        name=name,
        price=price,
        change=change,
        change_pct=change_pct,
        currency="KRW",
        source="naver",
        as_of=as_of,
        market_state=market_state,
    )


def _try_apply_krx_login() -> None:
    try:
        from engines.match.match.krx_io import apply_krx_login

        apply_krx_login()
    except Exception as exc:  # noqa: BLE001
        logger.debug("KRX login skipped: %s", exc)


def _fetch_pykrx_index(name: str, ticker: str) -> MarketQuote | None:
    try:
        from pykrx import stock
    except ImportError:
        return None

    _try_apply_krx_login()

    end = datetime.now(tz=KST).strftime("%Y%m%d")
    start = (datetime.now(tz=KST) - timedelta(days=14)).strftime("%Y%m%d")

    try:
        df = stock.get_index_ohlcv_by_date(start, end, ticker, name_display=True)
    except Exception as exc:  # noqa: BLE001
        logger.debug("pykrx %s failed: %s", name, exc)
        return None

    if df is None or df.empty:
        return None

    latest = df.iloc[-1]
    close = float(latest["종가"])
    if close <= 0:
        return None

    prev_close = float(df.iloc[-2]["종가"]) if len(df) >= 2 else close
    change = close - prev_close
    change_pct = _pct_change(close, prev_close)
    as_of = df.index[-1]
    if hasattr(as_of, "strftime"):
        as_of_label = as_of.strftime("%Y-%m-%d")
    else:
        as_of_label = str(as_of)

    return MarketQuote(
        name=name,
        price=close,
        change=change,
        change_pct=change_pct,
        currency="KRW",
        source="pykrx",
        as_of=f"{as_of_label} 종가 (KRX)",
        market_state="CLOSE",
    )


def _fetch_yahoo_quote(name: str, symbol: str) -> MarketQuote | None:
    last_error: Exception | None = None
    for chart_url in _YAHOO_CHART_URLS:
        try:
            resp = requests.get(
                chart_url.format(symbol=symbol),
                params={"interval": "1d", "range": "5d"},
                headers=_YAHOO_HEADERS,
                timeout=15,
            )
            resp.raise_for_status()
            payload = resp.json()
            result = (payload.get("chart") or {}).get("result") or []
            if not result:
                continue
            block = result[0]
            meta: dict[str, Any] = block.get("meta") or {}
            break
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            continue
    else:
        logger.debug("yahoo %s failed: %s", name, last_error)
        return None

    price = meta.get("regularMarketPrice")
    if price is None:
        return None
    price_f = float(price)

    # chartPreviousClose(meta)는 range=5d일 때 며칠 전 종가가 들어갈 수 있다.
    # 일봉 close 배열 + regularMarketPrice로 전 거래일 종가를 맞춘다.
    prev_f: float | None = None
    closes = (block.get("indicators") or {}).get("quote", [{}])[0].get("close") or []
    valid_closes = [float(c) for c in closes if c is not None]
    tolerance = max(0.05, price_f * 0.0001)

    if len(valid_closes) >= 2 and abs(valid_closes[-1] - price_f) <= tolerance:
        prev_f = valid_closes[-2]
    elif len(valid_closes) >= 1 and abs(valid_closes[-1] - price_f) > tolerance:
        # 최신 regularMarketPrice가 아직 일봉 배열 마지막에 반영되지 않은 경우
        prev_f = valid_closes[-1]
    else:
        raw_prev = meta.get("previousClose") or meta.get("chartPreviousClose")
        if raw_prev is not None:
            prev_f = float(raw_prev)

    if prev_f is None:
        prev_f = price_f

    change = price_f - prev_f
    change_pct = _pct_change(price_f, prev_f)

    currency = str(meta.get("currency") or "")
    exchange = str(meta.get("exchangeName") or meta.get("fullExchangeName") or "")
    market_state = str(meta.get("marketState") or "")
    ts = meta.get("regularMarketTime")
    as_of = exchange or "Yahoo Finance"
    if ts:
        dt = datetime.fromtimestamp(int(ts), tz=KST)
        as_of = f"{dt.strftime('%Y-%m-%d %H:%M')} KST ({exchange or 'Yahoo'})"

    return MarketQuote(
        name=name,
        price=price_f,
        change=change,
        change_pct=change_pct,
        currency=currency,
        source="yahoo",
        as_of=as_of,
        market_state=market_state or None,
    )


def _fetch_domestic_index(name: str) -> MarketQuote | None:
    naver_code = _NAVER_INDEX_CODES.get(name)
    if naver_code:
        quote = _fetch_naver_index(name, naver_code)
        if quote is not None:
            return quote

    symbol = _YAHOO_SYMBOLS.get(name)
    if symbol:
        quote = _fetch_yahoo_quote(name, symbol)
        if quote is not None:
            return quote

    if not _has_krx_credentials():
        return None

    ticker = _PYKRX_INDICES.get(name)
    if ticker:
        quote = _fetch_pykrx_index(name, ticker)
        if quote is not None:
            return quote

    return None


def _fetch_yahoo_only(name: str) -> MarketQuote | None:
    symbol = _YAHOO_SYMBOLS.get(name)
    if not symbol:
        return None
    return _fetch_yahoo_quote(name, symbol)


def fetch_market_snapshot(
    now_kst: str | None = None,
    *,
    include_commodities: bool = True,
) -> MarketSnapshot:
    """지수·환율·(선택) 원자재 시세를 조회한다."""
    if now_kst is None:
        now_kst = datetime.now(tz=KST).strftime("%Y-%m-%d %H:%M KST")

    snapshot = MarketSnapshot(fetched_at=now_kst)
    targets: list[tuple[str, str]] = [
        ("코스피", "domestic"),
        ("코스닥", "domestic"),
        ("S&P500", "yahoo"),
        ("나스닥", "yahoo"),
        ("닛케이225", "yahoo"),
        ("USD/KRW", "yahoo"),
    ]
    if include_commodities:
        targets.extend(
            [
                ("WTI", "yahoo"),
                ("금", "yahoo"),
                ("은", "yahoo"),
            ]
        )

    for name, kind in targets:
        quote: MarketQuote | None
        if kind == "domestic":
            quote = _fetch_domestic_index(name)
        else:
            quote = _fetch_yahoo_only(name)

        if quote is None:
            snapshot.errors.append(f"{name}: 시세 조회 실패")
            continue
        snapshot.quotes.append(quote)

    return snapshot


def _format_change(quote: MarketQuote) -> str:
    if quote.change is None or quote.change_pct is None:
        return "—"
    sign = "+" if quote.change >= 0 else ""
    return f"{sign}{quote.change:,.2f} ({sign}{quote.change_pct:.2f}%)"


def _format_price(quote: MarketQuote) -> str:
    if quote.price is None:
        return "—"
    if quote.name == "USD/KRW":
        return f"{quote.price:,.2f}원"
    if quote.currency == "KRW":
        return f"{quote.price:,.2f}p"
    if quote.currency == "USD" and quote.name in {"WTI", "금", "은"}:
        return f"${quote.price:,.2f}"
    return f"{quote.price:,.2f}"


def format_market_data_block(snapshot: MarketSnapshot) -> str:
    """Gemini user prompt에 넣을 실측 시세 블록."""
    if not snapshot.quotes:
        return (
            "## verified_market_data\n"
            "실측 시세를 가져오지 못했습니다. "
            "지수 표의 수치는 모두 `—` 또는 `확인 필요`로 표기하세요.\n"
            f"조회 오류: {', '.join(snapshot.errors) or '알 수 없음'}"
        )

    lines = [
        "## verified_market_data",
        f"조회 시각: {snapshot.fetched_at}",
        "",
        "아래 수치는 API 실측값이다. `## 1) 지수 요약` 표에서 해당 항목은 "
        "**반드시 이 숫자만** 사용하고, 소수점 자리도 임의로 바꾸지 마라. "
        "국내 지수(코스피·코스닥)는 네이버금융 실시간·종가 기준이며 장중이면 현재가를 쓴다.",
        "verified_market_data에 없는 행만 `—` 또는 `확인 필요`로 둬라.",
        "",
        "| 지수 | 현재가 | 전일대비 | 출처 | 시점 |",
        "|---|---|---|---|---|",
    ]

    for quote in snapshot.quotes:
        lines.append(
            f"| {quote.name} | {_format_price(quote)} | {_format_change(quote)} "
            f"| {quote.source} | {quote.as_of} |"
        )

    if snapshot.errors:
        lines.extend(["", f"조회 실패 항목: {', '.join(snapshot.errors)}"])

    lines.extend(
        [
            "",
            "원자재(WTI·금·은)가 위 표에 있으면 지수 요약 표 하단 또는 별도 행으로 포함해도 된다.",
        ]
    )
    return "\n".join(lines)


_INDEX_TABLE_NAMES = frozenset(
    {
        "코스피",
        "코스닥",
        "S&P500",
        "나스닥",
        "닛케이225",
        "USD/KRW",
        "WTI",
        "금",
        "은",
    }
)

_INDEX_ALIASES: dict[str, str] = {
    "S&P 500": "S&P500",
    "SP500": "S&P500",
    "NASDAQ": "나스닥",
    "Nasdaq": "나스닥",
    "Nikkei225": "닛케이225",
    "Nikkei 225": "닛케이225",
    "USD/KRW": "USD/KRW",
    "원/달러": "USD/KRW",
}

_INDEX_SECTION_ORDER: tuple[tuple[str, str], ...] = (
    ("코스피", "국내"),
    ("코스닥", "국내"),
    ("S&P500", "해외"),
    ("나스닥", "해외"),
    ("닛케이225", "해외"),
    ("USD/KRW", "환율"),
    ("WTI", "원자재"),
    ("금", "원자재"),
    ("은", "원자재"),
)

_CORE_INDEX_NAMES = ("코스피", "코스닥", "S&P500", "나스닥", "USD/KRW")


def _canonical_index_name(value: str) -> str | None:
    cleaned = value.strip()
    if cleaned in _INDEX_TABLE_NAMES:
        return cleaned
    return _INDEX_ALIASES.get(cleaned)


def _index_name_from_cells(cells: list[str]) -> str | None:
    for cell in cells[:3]:
        name = _canonical_index_name(cell)
        if name is not None:
            return name
    return None


def _build_verified_index_table(snapshot: MarketSnapshot) -> list[str]:
    quote_by_name = {quote.name: quote for quote in snapshot.quotes}
    lines = [
        "| 구분 | 지수 | 현재가 | 전일대비 | 코멘트 |",
        "|---|---|---|---|---|",
    ]
    for name, category in _INDEX_SECTION_ORDER:
        quote = quote_by_name.get(name)
        if quote is None or quote.price is None:
            continue
        lines.append(
            f"| {category} | {name} | {_format_price(quote)} "
            f"| {_format_table_change(quote)} | |"
        )
    lines.append("")
    lines.append(_format_data_timing_line(snapshot))
    return lines


def _replace_index_section(report: str, snapshot: MarketSnapshot) -> str:
    lines = report.splitlines()
    out: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if line.strip().startswith("## 1)"):
            out.append(line)
            out.append("")
            out.extend(_build_verified_index_table(snapshot))
            index += 1
            while index < len(lines) and not lines[index].strip().startswith("## 2)"):
                index += 1
            continue
        out.append(line)
        index += 1
    return "\n".join(out)


def _format_table_change(quote: MarketQuote) -> str:
    if quote.change is None or quote.change_pct is None:
        return "—"
    sign = "+" if quote.change >= 0 else ""
    return f"{sign}{quote.change:,.2f} ({sign}{quote.change_pct:.2f}%)"


def _format_data_timing_line(snapshot: MarketSnapshot) -> str:
    domestic_bits: list[str] = []
    for name in ("코스피", "코스닥"):
        quote = snapshot.quote_by_name(name)
        if quote is None:
            continue
        state = (
            "장중"
            if (quote.market_state or "").upper() == "OPEN"
            else "종가"
        )
        domestic_bits.append(f"{name} {state} ({quote.as_of})")

    overseas = [
        name
        for name in ("S&P500", "나스닥", "닛케이225")
        if snapshot.quote_by_name(name) is not None
    ]
    body = " · ".join(domestic_bits) if domestic_bits else snapshot.fetched_at
    if overseas:
        body += f" / 해외({', '.join(overseas)})는 표 시점 기준"
    return f"> 데이터 시점: {body}"


def apply_verified_quotes_to_report(
    report: str,
    snapshot: MarketSnapshot,
) -> str:
    """LLM 출력의 `## 1) 지수 요약` 표에 실측 시세를 강제 반영한다."""
    if not snapshot.quotes:
        return report

    quote_by_name = {quote.name: quote for quote in snapshot.quotes}
    lines = report.splitlines()
    out: list[str] = []
    in_index_section = False
    patched_count = 0

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## 1)"):
            in_index_section = True
            out.append(line)
            continue
        if in_index_section and stripped.startswith("## 2)"):
            in_index_section = False
        if (
            in_index_section
            and stripped.startswith("|")
            and not stripped.startswith("|---")
            and "지수" not in stripped
        ):
            cells = [cell.strip() for cell in stripped.strip("|").split("|")]
            index_name = _index_name_from_cells(cells) if len(cells) >= 3 else None
            if index_name is not None:
                quote = quote_by_name.get(index_name)
                if quote is not None and quote.price is not None:
                    if len(cells) >= 5 and _canonical_index_name(cells[1]) == index_name:
                        price_col, change_col = 2, 3
                    elif _canonical_index_name(cells[0]) == index_name:
                        price_col, change_col = 1, 2
                    else:
                        price_col, change_col = 2, 3
                    if len(cells) > change_col:
                        cells[price_col] = _format_price(quote)
                        cells[change_col] = _format_table_change(quote)
                        line = "| " + " | ".join(cells) + " |"
                        patched_count += 1
        if in_index_section and stripped.startswith("> 데이터 시점"):
            line = _format_data_timing_line(snapshot)
        out.append(line)

    result = "\n".join(out)
    core_available = sum(
        1 for name in _CORE_INDEX_NAMES if quote_by_name.get(name) is not None
    )
    if core_available and patched_count < min(2, core_available):
        return _replace_index_section(report, snapshot)
    return result
