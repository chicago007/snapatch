"""breaker 시세 조회·프롬프트 포맷 테스트."""

from __future__ import annotations

from engines.breaker.market_data import (
    MarketQuote,
    MarketSnapshot,
    _pct_change,
    apply_verified_quotes_to_report,
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


def test_apply_verified_quotes_to_report_patches_index_table() -> None:
    snapshot = MarketSnapshot(
        fetched_at="2026-07-07 10:42 KST",
        quotes=[
            MarketQuote(
                name="코스피",
                price=7641.99,
                change=-409.34,
                change_pct=-5.08,
                currency="KRW",
                source="naver",
                as_of="2026-07-07 10:42 KST (네이버금융)",
                market_state="OPEN",
            ),
            MarketQuote(
                name="S&P500",
                price=7537.43,
                change=54.19,
                change_pct=0.72,
                currency="USD",
                source="yahoo",
                as_of="2026-07-07 05:43 KST (SNP)",
            ),
        ],
    )
    report = "\n".join(
        [
            "## 1) 지수 요약",
            "| 구분 | 지수 | 현재가 | 전일대비 | 코멘트 |",
            "|---|---|---|---|---|",
            "| 국내 | 코스피 | 8,051.33p | -343.32 (-4.09%) | 잘못된 값 |",
            "| 해외 | S&P500 | 7,537.43 | +183.41 (+2.49%) | 잘못된 값 |",
            "",
            "> 데이터 시점: 예시",
            "",
            "## 2) 섹터 / 테마 요약",
        ]
    )
    patched = apply_verified_quotes_to_report(report, snapshot)
    assert "7,641.99p" in patched
    assert "-409.34 (-5.08%)" in patched
    assert "+54.19 (+0.72%)" in patched
    assert "8,051.33p" not in patched
    assert "+2.49%" not in patched
    assert "장중" in patched
