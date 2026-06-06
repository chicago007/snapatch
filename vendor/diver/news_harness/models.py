from __future__ import annotations

from datetime import datetime
from typing import Literal, List
from pydantic import BaseModel, Field

class NewsItem(BaseModel):
    title: str
    url: str
    press: str = ""
    published_at: datetime
    description: str = ""
    content: str = ""

class RelatedKeyword(BaseModel):
    keyword: str = Field(description="관련 키워드")
    type: Literal["technology", "company", "theme", "event"]
    reason: str

class AnalyzedNewsItem(BaseModel):
    published_at: str
    title: str
    press: str
    summary: str
    sentiment: Literal["positive", "negative", "neutral"]
    impact: Literal["short_term", "mid_term", "unclear"]
    keywords: List[str]
    url: str

class AnalysisResult(BaseModel):
    query: str
    searched_days: int
    news: List[AnalyzedNewsItem]
    overall_summary: str
    related_keywords: List[RelatedKeyword]
