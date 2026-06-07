from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any, List

from article_parser import extract_article_text
from config import Settings
from gemini_analyzer import GeminiNewsAnalyzer
from models import AnalysisResult, NewsItem
from naver_client import NaverNewsClient
from post_filter import filter_analyzed_similar_news


def fill_article_contents(
    news_items: List[NewsItem],
    skip_content: bool = False,
    timeout_seconds: float = 3.0,
    max_workers: int = 5,
) -> None:
    if skip_content:
        for item in news_items:
            item.content = item.description
        return

    worker_count = min(len(news_items), max_workers)
    if worker_count <= 0:
        return

    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        contents = list(
            executor.map(
                lambda item: extract_article_text(
                    item.url,
                    fallback=item.description,
                    timeout_seconds=timeout_seconds,
                ),
                news_items,
            ),
        )

    for item, content in zip(news_items, contents):
        item.content = content


def run_pipeline(
    query: str,
    target_count: int = 5,
    max_days: int = 30,
    debug: bool = False,
    skip_content: bool | None = None,
) -> AnalysisResult | dict[str, Any] | tuple[AnalysisResult | dict[str, Any], List[NewsItem]]:
    settings = Settings()
    naver = NaverNewsClient(settings)
    analyzer = GeminiNewsAnalyzer(settings)
    should_skip_content = settings.skip_content if skip_content is None else skip_content
    news_items, searched_days = naver.collect_latest_news(
        query=query,
        target_count=target_count,
        max_days=max_days,
    )
    fill_article_contents(
        news_items,
        skip_content=should_skip_content,
        timeout_seconds=settings.article_timeout_seconds,
        max_workers=settings.article_max_workers,
    )
    result = analyzer.analyze(
        query=query,
        news_items=news_items,
        searched_days=searched_days,
    )
    if settings.post_filter_similar_news and isinstance(result, AnalysisResult):
        dedup_news = filter_analyzed_similar_news(
            result.news,
            overlap_threshold=settings.post_news_keyword_overlap_threshold,
            min_common_keywords=settings.post_news_keyword_min_common,
        )
        result = result.model_copy(update={"news": dedup_news})

    return (result, news_items) if debug else result
