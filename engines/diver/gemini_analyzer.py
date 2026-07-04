from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, List

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None

from google import genai

from config import Settings
from models import NewsItem


class GeminiNewsAnalyzer:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.settings.validate_vertex()
        # Default (beta) API — v1 stable endpoints reject response_schema / response_mime_type.
        self.client = genai.Client()
        self.base_prompt = self._load_base_prompt()

    @staticmethod
    def _load_base_prompt() -> str:
        project_root = Path(__file__).resolve().parent
        return (project_root / "prompt.md").read_text(encoding="utf-8").strip()

    @staticmethod
    def _get_kst_datetime() -> datetime:
        if ZoneInfo is not None:
            try:
                return datetime.now(ZoneInfo("Asia/Seoul"))
            except Exception:
                pass
        return datetime.now(timezone(timedelta(hours=9)))

    @staticmethod
    def _get_korean_weekday(value: datetime) -> str:
        return {
            0: "월요일",
            1: "화요일",
            2: "수요일",
            3: "목요일",
            4: "금요일",
            5: "토요일",
            6: "일요일",
        }[value.weekday()]

    @staticmethod
    def _schema() -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "analysis_reference_datetime_kst": {"type": "string"},
                "analysis_reference_weekday_kst": {"type": "string"},
                "query": {"type": "string"},
                "searched_days": {"type": "integer"},
                "keyword_interpretation": {
                    "type": "object",
                    "properties": {
                        "classification": {"type": "string"},
                        "definition": {"type": "string"},
                        "background": {"type": "string"},
                    },
                    "required": ["classification", "definition", "background"],
                },
                "news_scan_results": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "integer"},
                            "date": {"type": "string"},
                            "source": {"type": "string"},
                            "headline": {"type": "string"},
                            "summary": {"type": "string"},
                            "sentiment": {"type": "string"},
                        },
                        "required": [
                            "id",
                            "date",
                            "source",
                            "headline",
                            "summary",
                            "sentiment",
                        ],
                    },
                },
                "fact_analysis": {"type": "array", "items": {"type": "string"}},
                "market_psychology_analysis": {
                    "type": "object",
                    "properties": {
                        "fear_greed_index": {"type": "integer"},
                        "summary": {"type": "string"},
                        "biases": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["fear_greed_index", "summary", "biases"],
                },
                "narrative_analysis": {"type": "string"},
                "market_impact_analysis": {
                    "type": "object",
                    "properties": {
                        "direct_impact": {"type": "array", "items": {"type": "string"}},
                        "indirect_impact": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["direct_impact", "indirect_impact"],
                },
                "risk_opportunity_matrix": {
                    "type": "object",
                    "properties": {
                        "upside_factors": {"type": "array", "items": {"type": "string"}},
                        "downside_factors": {"type": "array", "items": {"type": "string"}},
                        "black_swans": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["upside_factors", "downside_factors", "black_swans"],
                },
                "investment_scenarios": {
                    "type": "object",
                    "properties": {
                        "bull_scenario": {"type": "string"},
                        "base_scenario": {"type": "string"},
                        "bear_scenario": {"type": "string"},
                    },
                    "required": [
                        "bull_scenario",
                        "base_scenario",
                        "bear_scenario",
                    ],
                },
                "investment_action_plan": {
                    "type": "object",
                    "properties": {
                        "entry_timing": {"type": "string"},
                        "profit_taking": {"type": "string"},
                        "stop_loss": {"type": "string"},
                        "monitoring_indicators": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                    },
                    "required": [
                        "entry_timing",
                        "profit_taking",
                        "stop_loss",
                        "monitoring_indicators",
                    ],
                },
                "final_assessment": {
                    "type": "object",
                    "properties": {
                        "one_liner_message": {"type": "string"},
                        "strengths": {"type": "array", "items": {"type": "string"}},
                        "weaknesses": {"type": "array", "items": {"type": "string"}},
                        "final_recommendation": {"type": "string"},
                    },
                    "required": [
                        "one_liner_message",
                        "strengths",
                        "weaknesses",
                        "final_recommendation",
                    ],
                },
                "analysis_completion_datetime_kst": {"type": "string"},
                "reliability_grade": {"type": "string"},
                "next_monitoring_date": {"type": "string"},
                "monitoring_reason": {"type": "string"},
            },
            "required": [
                "analysis_reference_datetime_kst",
                "analysis_reference_weekday_kst",
                "query",
                "searched_days",
                "keyword_interpretation",
                "news_scan_results",
                "fact_analysis",
                "market_psychology_analysis",
                "narrative_analysis",
                "market_impact_analysis",
                "risk_opportunity_matrix",
                "investment_scenarios",
                "investment_action_plan",
                "final_assessment",
                "analysis_completion_datetime_kst",
                "reliability_grade",
                "next_monitoring_date",
                "monitoring_reason",
            ],
        }

    def _build_prompt(
        self,
        query: str,
        searched_days: int,
        compact_news: list[dict[str, Any]],
    ) -> str:
        now_kst = self._get_kst_datetime()
        weekday = self._get_korean_weekday(now_kst)
        return (
            f"{self.base_prompt}\n\n"
            "위 prompt.md의 투자 리서치 의도를 따르되, 출력은 아래 고정 JSON "
            "스키마에 맞춘 간략 버전으로 작성하라.\n"
            "마크다운, 표, 코드블록, 설명문은 출력하지 마라.\n"
            "모든 키는 영어 snake_case로만 작성하라.\n"
            "모든 배열은 가능한 한 3개 항목 이상 채워라.\n"
            "불확실한 내용은 추정하지 말고 '불확실함'이라고 써라.\n"
            "아래 기준 시각과 요일은 절대 바꾸지 말고 그대로 출력하라.\n\n"
            f"analysis_reference_datetime_kst: {now_kst.isoformat()}\n"
            f"analysis_reference_weekday_kst: {weekday}\n"
            f"query: {query}\n"
            f"searched_days: {searched_days}\n"
            "news_items:\n"
            f"{json.dumps(compact_news, ensure_ascii=False)}"
        )

    def analyze(
        self,
        query: str,
        news_items: List[NewsItem],
        searched_days: int,
    ) -> dict[str, Any]:
        compact_news = [
            {
                "published_at": item.published_at.isoformat(),
                "title": item.title,
                "press": item.press,
                "url": item.url,
                "description": item.description,
                "content": item.content[: self.settings.content_preview_length],
            }
            for item in news_items
        ]
        response = self.client.models.generate_content(
            model=self.settings.vertex_model,
            contents=self._build_prompt(query, searched_days, compact_news),
            config={
                "response_mime_type": "application/json",
                "response_schema": self._schema(),
            },
        )
        payload = json.loads(response.text)
        if not isinstance(payload, dict):
            raise ValueError("LLM 응답은 JSON 객체 1개여야 합니다.")
        return payload
