from datetime import datetime, timedelta
from dateutil import tz

from engines.diver.models import NewsItem
from engines.diver.naver_client import filter_similar_news

KST = tz.gettz("Asia/Seoul")


def filter_expand(items, target_count=5, max_days=30):
    now = datetime.now(KST)
    dedup = {}
    searched_days = 0
    for day_span in range(1, max_days + 1):
        floor = (now - timedelta(days=day_span - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
        for item in items:
            if floor <= item.published_at <= now:
                dedup[item.url] = item
        searched_days = day_span
        if len(dedup) >= target_count:
            break
    return sorted(dedup.values(), key=lambda x: x.published_at, reverse=True)[:target_count], searched_days


def test_expand_days_until_target_count():
    now = datetime.now(KST)
    items = [NewsItem(title=f"n{i}", url=f"u{i}", published_at=now - timedelta(days=i), description="") for i in range(4)]
    result, searched_days = filter_expand(items, target_count=4, max_days=30)
    assert len(result) == 4
    assert searched_days == 4


def test_limit_to_five_latest():
    now = datetime.now(KST)
    items = [NewsItem(title=f"n{i}", url=f"u{i}", published_at=now - timedelta(hours=i), description="") for i in range(10)]
    result, searched_days = filter_expand(items, target_count=5, max_days=30)
    assert len(result) == 5
    assert result[0].published_at > result[-1].published_at
    assert searched_days == 1


def test_filter_similar_news_keeps_latest_distinct_items():
    now = datetime.now(KST)
    items = [
        NewsItem(
            title="삼성전자 HBM 공급 확대",
            url="u1",
            published_at=now,
            description="삼성전자가 HBM 공급 확대를 추진한다.",
        ),
        NewsItem(
            title="삼성전자 HBM 공급 확대",
            url="u2",
            published_at=now - timedelta(minutes=1),
            description="삼성전자가 HBM 공급 확대를 추진한다.",
        ),
        NewsItem(
            title="중동 원유 가격 상승",
            url="u3",
            published_at=now - timedelta(minutes=2),
            description="중동 리스크로 국제유가가 상승했다.",
        ),
    ]

    result = filter_similar_news(items, target_count=3, threshold=0.82)

    assert [item.url for item in result] == ["u1", "u3"]


def test_filter_similar_news_removes_token_overlap_duplicates():
    now = datetime.now(KST)
    items = [
        NewsItem(
            title="중동 리스크에 국제유가 급등",
            url="u1",
            published_at=now,
            description="중동 리스크 확대로 원유 공급 우려가 커졌다.",
        ),
        NewsItem(
            title="국제유가 상승, 중동 원유 공급 우려 부각",
            url="u2",
            published_at=now - timedelta(minutes=1),
            description="중동 리스크와 원유 공급 우려가 유가를 끌어올렸다.",
        ),
        NewsItem(
            title="삼성전자 반도체 투자 확대",
            url="u3",
            published_at=now - timedelta(minutes=2),
            description="삼성전자가 반도체 설비 투자를 늘린다.",
        ),
    ]

    result = filter_similar_news(
        items,
        target_count=3,
        threshold=0.82,
        token_overlap_threshold=0.45,
    )

    assert [item.url for item in result] == ["u1", "u3"]
