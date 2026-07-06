"""breaker 시세 조회·프롬프트 포맷 테스트."""

from __future__ import annotations

from engines.breaker.market_data import (
    MarketQuote,
    MarketSnapshot,
    _pct_change,
    format_market_data_block,
)


def test_pct_change() -> None:
    assert _pct_change(110, 100) == 10.0
    assert round(_pct_change(99, 100), 2) == -1.0


def test_format_market_data_block_includes_verified_prices() -> None:
    snapshot = MarketSnapshot(
        fetched_at="2026-07-06 13:00 KST",
        quotes=[
            MarketQuote(
                name="코스피",
                price=8051.33,
                change=-37.01,
                change_pct=-0.46,
                currency="KRW",
                source="yahoo",
                as_of="2026-07-06 13:00 KST",
            ),
        ],
    )
    block = format_market_data_block(snapshot)
    assert "verified_market_data" in block
    assert "8,051.33p" in block
    assert "-0.46%" in block
    assert "반드시 이 숫자만" in block


def test_format_market_data_block_empty_snapshot() -> None:
    snapshot = MarketSnapshot(
        fetched_at="2026-07-06 13:00 KST",
        errors=["코스피: 시세 조회 실패"],
    )
    block = format_market_data_block(snapshot)
    assert "가져오지 못했습니다" in block
    assert "코스피" in block
