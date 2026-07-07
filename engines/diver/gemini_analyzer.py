from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, List

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None

from google import genai
from google.genai import types
from google.genai.types import HttpOptions

from .config import Settings
from .models import NewsItem

_MAX_OUTPUT_ATTEMPTS = 3
_DEFAULT_MAX_OUTPUT_TOKENS = 16384
_RETRY_MAX_OUTPUT_TOKENS = 32768
_LLM_CONTENT_PREVIEW_CAP = 500

_RETRY_COMPACT_HINTS = (
    "",
    (
        "\n\n[중요] 이전 응답이 출력 한도로 잘렸습니다. "
        "모든 문자열 필드를 200자 이내로 줄이고, "
        "news_scan_results는 제공된 기사 수만큼만 작성하며, "
        "각 배열은 3~5개 항목으로 제한하세요. JSON을 반드시 완결하세요."
    ),
    (
        "\n\n[최종 재시도] 극도로 간결하게 작성하세요. "
        "narrative_analysis 150자, 시나리오 각 100자, summary·headline 80자 이내."
    ),
)


def _build_genai_client(settings: Settings) -> genai.Client:
    if settings.uses_vertexai():
        return genai.Client(
            vertexai=True,
            project=settings.google_cloud_project,
            location=settings.google_cloud_location,
            http_options=HttpOptions(api_version="v1beta1"),
        )

    api_key = (os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY") or "").strip()
    return genai.Client(
        api_key=api_key,
        http_options=HttpOptions(api_version="v1beta"),
    )


class GeminiNewsAnalyzer:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.settings.validate_gemini()
        self.client = _build_genai_client(settings)
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
            "스키마에 맞춰 작성하라.\n"
            "마크다운, 표, 코드블록, 설명문은 출력하지 마라.\n"
            "모든 키는 영어 snake_case로만 작성하라.\n"
            "모든 배열은 3~5개 항목으로 채워라.\n"
            "각 문자열 필드는 250자 이내로 간결하게 작성하라.\n"
            "불확실한 내용은 추정하지 말고 '불확실함'이라고 한 번만 표기하라.\n"
            "아래 기준 시각과 요일은 절대 바꾸지 말고 그대로 출력하라.\n\n"
            f"analysis_reference_datetime_kst: {now_kst.isoformat()}\n"
            f"analysis_reference_weekday_kst: {weekday}\n"
            f"query: {query}\n"
            f"searched_days: {searched_days}\n"
            "news_items:\n"
            f"{json.dumps(compact_news, ensure_ascii=False)}"
        )

    @classmethod
    def _sanitize_text(cls, text: str, max_len: int = 500) -> str:
        if not text:
            return text
        cleaned = re.sub(r"(?:불확실함[.\s]*){2,}", "불확실함. ", str(text).strip())
        if len(cleaned) > max_len:
            cleaned = cleaned[:max_len].rstrip(".,; ") + "…"
        return cleaned

    @classmethod
    def _sanitize_payload(cls, data: dict[str, Any]) -> dict[str, Any]:
        def walk(obj: Any) -> Any:
            if isinstance(obj, str):
                return cls._sanitize_text(obj)
            if isinstance(obj, list):
                return [walk(item) for item in obj]
            if isinstance(obj, dict):
                return {key: walk(value) for key, value in obj.items()}
            return obj

        cleaned = walk(data)
        return cleaned if isinstance(cleaned, dict) else data

    @staticmethod
    def _response_finish_reason(response: Any) -> str:
        try:
            candidates = getattr(response, "candidates", None) or []
            if candidates:
                reason = getattr(candidates[0], "finish_reason", None)
                if reason is not None:
                    return str(reason).upper()
        except Exception:
            pass
        return ""

    @classmethod
    def _response_truncated(cls, response: Any) -> bool:
        return "MAX_TOKEN" in cls._response_finish_reason(response)

    @staticmethod
    def _parse_response_json(response: Any) -> dict[str, Any]:
        parsed = getattr(response, "parsed", None)
        if isinstance(parsed, dict):
            return parsed

        text = (getattr(response, "text", None) or "").strip()
        if not text:
            raise json.JSONDecodeError("empty LLM response", text, 0)
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
            text = re.sub(r"\s*```\s*$", "", text)

        payload = json.loads(text)
        if not isinstance(payload, dict):
            raise ValueError("LLM 응답은 JSON 객체 1개여야 합니다.")
        return payload

    def analyze(
        self,
        query: str,
        news_items: List[NewsItem],
        searched_days: int,
    ) -> dict[str, Any]:
        llm_preview = min(
            self.settings.content_preview_length,
            _LLM_CONTENT_PREVIEW_CAP,
        )
        compact_news = [
            {
                "published_at": item.published_at.isoformat(),
                "title": item.title,
                "press": item.press,
                "url": item.url,
                "description": item.description[:llm_preview],
                "content": item.content[:llm_preview],
            }
            for item in news_items
        ]
        base_prompt = self._build_prompt(query, searched_days, compact_news)
        schema = self._schema()
        last_error: Exception | None = None
        response: Any = None

        for attempt, hint in enumerate(_RETRY_COMPACT_HINTS[:_MAX_OUTPUT_ATTEMPTS]):
            prompt = f"{base_prompt}{hint}" if hint else base_prompt
            max_tokens = (
                _RETRY_MAX_OUTPUT_TOKENS
                if attempt >= 1
                else _DEFAULT_MAX_OUTPUT_TOKENS
            )
            response = self.client.models.generate_content(
                model=self.settings.vertex_model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_json_schema=schema,
                    max_output_tokens=max_tokens,
                ),
            )
            try:
                payload = self._parse_response_json(response)
            except (json.JSONDecodeError, ValueError) as exc:
                last_error = exc
                continue
            return self._sanitize_payload(payload)

        preview = (getattr(response, "text", None) or "")[:500].replace("\n", " ")
        finish = self._response_finish_reason(response) if response is not None else ""
        detail = f"finish_reason={finish or 'unknown'}" if finish else ""
        raise ValueError(
            f"LLM JSON 파싱 실패: {last_error}. {detail} 응답 앞부분: {preview}"
        ) from last_error
