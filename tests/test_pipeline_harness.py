from datetime import datetime
from dateutil import tz

from engines.diver.models import AnalysisResult, AnalyzedNewsItem, NewsItem, RelatedKeyword
from engines.diver.pipeline import fill_article_contents

KST = tz.gettz("Asia/Seoul")


def test_pipeline_contract_shape():
    raw = [
        NewsItem(
            title="삼성전자 HBM 공급 확대",
            url="https://example.com/1",
            press="테스트",
            published_at=datetime(2026, 5, 2, 10, 0, tzinfo=KST),
            description="HBM 관련 뉴스",
            content="삼성전자가 HBM 공급 확대를 추진한다."
        )
    ]
    result = AnalysisResult(
        query="삼성전자",
        searched_days=1,
        news=[
            AnalyzedNewsItem(
                published_at="2026-05-02T10:00:00+09:00",
                title=raw[0].title,
                press=raw[0].press,
                summary="HBM 공급 확대 기대가 부각됐다.",
                sentiment="positive",
                impact="short_term",
                keywords=["HBM", "반도체"],
                url=raw[0].url,
            )
        ],
        overall_summary="메모리 관련 기대감이 핵심이다.",
        related_keywords=[RelatedKeyword(keyword="HBM", type="technology", reason="기사 핵심 주제")],
    )
    assert result.news[0].title == "삼성전자 HBM 공급 확대"
    assert result.related_keywords[0].type == "technology"


def test_fill_article_contents_can_skip_remote_fetch():
    items = [
        NewsItem(
            title="삼성전자 HBM 공급 확대",
            url="https://example.com/1",
            press="테스트",
            published_at=datetime(2026, 5, 2, 10, 0, tzinfo=KST),
            description="네이버 API 요약",
            content="",
        )
    ]

    fill_article_contents(items, skip_content=True)

    assert items[0].content == "네이버 API 요약"
