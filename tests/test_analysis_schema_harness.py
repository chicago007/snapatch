from engines.diver.models import AnalysisResult


def test_analysis_result_schema_minimal():
    payload = {
        "query": "삼성전자",
        "searched_days": 2,
        "news": [
            {
                "published_at": "2026-05-02T10:00:00+09:00",
                "title": "제목",
                "press": "연합뉴스",
                "summary": "요약",
                "sentiment": "neutral",
                "impact": "short_term",
                "keywords": ["HBM"],
                "url": "https://example.com"
            }
        ],
        "overall_summary": "전체 요약",
        "related_keywords": [
            {
                "keyword": "HBM",
                "type": "technology",
                "reason": "반복 언급"
            }
        ]
    }
    model = AnalysisResult.model_validate(payload)
    assert model.query == "삼성전자"
    assert model.related_keywords[0].keyword == "HBM"
