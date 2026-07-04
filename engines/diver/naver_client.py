from __future__ import annotations

import html
import re
from difflib import SequenceMatcher
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import List

import requests
from dateutil import tz

from .config import Settings
from .models import NewsItem

NAVER_NEWS_API = "https://openapi.naver.com/v1/search/news.json"
KST = tz.gettz("Asia/Seoul")
SIMILARITY_STOPWORDS = {
    "관련",
    "뉴스",
    "기자",
    "단독",
    "종합",
    "속보",
    "오늘",
    "지난",
    "이번",
    "대한",
    "통해",
    "밝혔다",
}


def clean_html(text: str) -> str:
    text = html.unescape(text or "")
    return re.sub(r"<[^>]+>", "", text).strip()


def normalize_for_similarity(text: str) -> str:
    text = clean_html(text).lower()
    text = re.sub(r"[^0-9a-z가-힣]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def get_similarity_text(item: NewsItem) -> str:
    return normalize_for_similarity(f"{item.title} {item.description}")


def get_similarity_tokens(item: NewsItem) -> set[str]:
    text = get_similarity_text(item)
    return {
        token
        for token in text.split()
        if len(token) >= 2 and token not in SIMILARITY_STOPWORDS
    }


def get_token_overlap_ratio(item: NewsItem, selected_item: NewsItem) -> float:
    item_tokens = get_similarity_tokens(item)
    selected_tokens = get_similarity_tokens(selected_item)
    if not item_tokens or not selected_tokens:
        return 0.0

    common_count = len(item_tokens & selected_tokens)
    if common_count < 3:
        return 0.0

    return common_count / min(len(item_tokens), len(selected_tokens))


def is_similar_news(
    item: NewsItem,
    selected_items: List[NewsItem],
    threshold: float,
    token_overlap_threshold: float,
) -> bool:
    item_text = get_similarity_text(item)
    if not item_text:
        return False

    for selected_item in selected_items:
        selected_text = get_similarity_text(selected_item)
        if SequenceMatcher(None, item_text, selected_text).ratio() >= threshold:
            return True
        if get_token_overlap_ratio(item, selected_item) >= token_overlap_threshold:
            return True

    return False


def filter_similar_news(
    news_items: List[NewsItem],
    target_count: int,
    threshold: float,
    token_overlap_threshold: float = 0.55,
) -> List[NewsItem]:
    selected_items: List[NewsItem] = []
    for item in news_items:
        if is_similar_news(
            item,
            selected_items,
            threshold,
            token_overlap_threshold,
        ):
            continue
        selected_items.append(item)
        if len(selected_items) >= target_count:
            break

    return selected_items


class NaverNewsClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.settings.validate_naver()
        self._session = requests.Session()
        self._session.headers.update({
            "X-Naver-Client-Id": self.settings.naver_client_id,
            "X-Naver-Client-Secret": self.settings.naver_client_secret,
        })

    def search(self, query: str, display: int = 100, start: int = 1, sort: str = "date") -> List[NewsItem]:
        params = {
            "query": query,
            "display": min(display, 100),
            "start": start,
            "sort": sort,
        }
        res = self._session.get(NAVER_NEWS_API, params=params, timeout=20)
        res.raise_for_status()
        payload = res.json()
        items = []
        for item in payload.get("items", []):
            published_at = parsedate_to_datetime(item["pubDate"]).astimezone(KST)
            items.append(
                NewsItem(
                    title=clean_html(item.get("title", "")),
                    url=item.get("originallink") or item.get("link") or "",
                    press="",
                    published_at=published_at,
                    description=clean_html(item.get("description", "")),
                    content="",
                )
            )
        return items

    def collect_latest_news(self, query: str, target_count: int = 5, max_days: int = 30) -> tuple[List[NewsItem], int]:
        now = datetime.now(KST)
        dedup = {}
        searched_days = 0
        batch = self.search(query=query, display=100, start=1, sort="date")

        for day_span in range(1, max_days + 1):
            floor = (now - timedelta(days=day_span - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
            for item in batch:
                if floor <= item.published_at <= now:
                    dedup[item.url or f"{item.title}-{item.published_at.isoformat()}"] = item
            searched_days = day_span
            if len(dedup) >= target_count:
                break

        results = sorted(dedup.values(), key=lambda x: x.published_at, reverse=True)
        if self.settings.filter_similar_news:
            return (
                filter_similar_news(
                    results,
                    target_count=target_count,
                    threshold=self.settings.news_similarity_threshold,
                    token_overlap_threshold=(
                        self.settings.news_token_overlap_threshold
                    ),
                ),
                searched_days,
            )

        return results[:target_count], searched_days
