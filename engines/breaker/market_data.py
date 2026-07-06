"""breaker용 실시간 시세 조회 — pykrx 우선, 불가 시 Yahoo Finance.

국내 지수(코스피·코스닥): pykrx(KRX) → Yahoo Finance(^KS11, ^KQ11)
해외 지수·환율·원자재: Yahoo Finance chart API (requests, 별도 패키지 불필요)

네이버 금융(finance.naver.com)은 비공식 polling API가 있으나
문서화·안정성이 없어 기본 체인에는 넣지 않았다.
"""

from __future__ import annotations

import logging
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
_YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"

# pykrx 지수 티커 (1001=코스피, 2001=코스닥)
_PYKRX_INDICES: dict[str, str] = {
    "코스피": "1001",
    "코스닥": "2001",
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
    try:
        resp = requests.get(
            _YAHOO_CHART_URL.format(symbol=symbol),
            params={"interval": "1d", "range": "5d"},
            headers=_YAHOO_HEADERS,
            timeout=15,
        )
        resp.raise_for_status()
        payload = resp.json()
        result = (payload.get("chart") or {}).get("result") or []
        if not result:
            return None
        block = result[0]
        meta: dict[str, Any] = block.get("meta") or {}
    except Exception as exc:  # noqa: BLE001
        logger.debug("yahoo %s failed: %s", name, exc)
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
    ticker = _PYKRX_INDICES.get(name)
    if ticker:
        quote = _fetch_pykrx_index(name, ticker)
        if quote is not None:
            return quote

    symbol = _YAHOO_SYMBOLS.get(name)
    if symbol:
        return _fetch_yahoo_quote(name, symbol)
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
        "**반드시 이 숫자만** 사용하고, 소수점 자리도 임의로 바꾸지 마라.",
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
