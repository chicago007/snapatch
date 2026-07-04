from engines.diver.models import AnalyzedNewsItem
from engines.diver.post_filter import filter_analyzed_similar_news


def _item(url: str, keywords: list[str]) -> AnalyzedNewsItem:
    return AnalyzedNewsItem(
        published_at="2026-05-02T18:00:00+09:00",
        title="t",
        press="",
        summary="s",
        sentiment="neutral",
        impact="unclear",
        keywords=keywords,
        url=url,
    )


def test_post_filter_removes_duplicate_issue_by_keywords():
    news = [
        _item(
            "u1",
            [
                "일본",
                "베트남",
                "광물 공급망",
                "원유 조달",
                "반도체",
                "에너지 자원 공급망",
            ],
        ),
        _item(
            "u2",
            [
                "일본",
                "베트남",
                "광물 공급망",
                "원유 조달",
                "반도체",
                "공급망",
            ],
        ),
    ]

    kept = filter_analyzed_similar_news(
        news,
        overlap_threshold=0.55,
        min_common_keywords=3,
    )

    assert len(kept) == 1
    assert kept[0].url == "u1"


def test_post_filter_keeps_distinct_articles():
    news = [
        _item(
            "u1",
            ["중동", "원유", "가격", "에너지"],
        ),
        _item(
            "u2",
            ["삼성전자", "반도체", "HBM"],
        ),
    ]

    kept = filter_analyzed_similar_news(
        news,
        overlap_threshold=0.55,
        min_common_keywords=3,
    )

    assert len(kept) == 2
