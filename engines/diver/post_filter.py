"""Gemini 분석 결과에서 키워드 겹침으로 같은 이슈 기사를 2차 제거합니다."""

from __future__ import annotations

from typing import List

from models import AnalyzedNewsItem


def _keyword_set(item: AnalyzedNewsItem) -> set[str]:
    result: set[str] = set()
    for kw in item.keywords:
        normalized = kw.strip()
        if normalized:
            result.add(normalized)
    return result


def _keyword_overlap_ratio(left: AnalyzedNewsItem, right: AnalyzedNewsItem) -> float:
    a = _keyword_set(left)
    b = _keyword_set(right)
    if not a or not b:
        return 0.0
    intersection = len(a & b)
    if intersection <= 0:
        return 0.0
    denominator = min(len(a), len(b))
    return intersection / denominator if denominator else 0.0


def filter_analyzed_similar_news(
    news: List[AnalyzedNewsItem],
    overlap_threshold: float,
    min_common_keywords: int,
) -> List[AnalyzedNewsItem]:
    kept: List[AnalyzedNewsItem] = []
    for item in news:
        is_dup = False
        for prev in kept:
            common = len(_keyword_set(item) & _keyword_set(prev))
            if common < min_common_keywords:
                continue
            ratio = _keyword_overlap_ratio(item, prev)
            if ratio >= overlap_threshold:
                is_dup = True
                break
        if not is_dup:
            kept.append(item)
    return kept
