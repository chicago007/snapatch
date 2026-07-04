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

    _UNCERTAINTY_PHRASE = "불확실함"
    _TEXT_MAX_LEN = 400

    @classmethod
    def _sanitize_repetition(cls, text: str, max_len: int | None = None) -> str:
        if not text:
            return text
        limit = max_len if max_len is not None else cls._TEXT_MAX_LEN
        s = str(text).strip()
        s = re.sub(
            rf"(?:{re.escape(cls._UNCERTAINTY_PHRASE)}[.\s]*){{2,}}",
            f"{cls._UNCERTAINTY_PHRASE}. ",
            s,
        )
        s = re.sub(r"(.{1,40}?)(?:\1){4,}", r"\1", s)
        s = re.sub(r"\s{2,}", " ", s).strip()
        if len(s) > limit:
            cut = s[:limit]
            if " " in cut[max(limit // 2, 1) :]:
                cut = cut[: cut.rfind(" ", 0, limit)]
            s = cut.rstrip(".,; ") + "…"
        return s

    @classmethod
    def _sanitize_payload(cls, data: dict[str, Any]) -> dict[str, Any]:
        def walk(obj: Any) -> Any:
            if isinstance(obj, str):
                return cls._sanitize_repetition(obj)
            if isinstance(obj, list):
                return [walk(item) for item in obj]
            if isinstance(obj, dict):
                return {key: walk(value) for key, value in obj.items()}
            return obj

        cleaned = walk(data)
        return cleaned if isinstance(cleaned, dict) else data

    def _build_prompt(
        self,
        query: str,
        searched_days: int,
        compact_news: list[dict[str, Any]],
        *,
        fast: bool = False,
    ) -> str:
        now_kst = self._get_kst_datetime()
        weekday = self._get_korean_weekday(now_kst)
        if fast:
            depth_rule = (
                "각 배열은 핵심 항목 2~3개를 채워라.\n"
                "문장은 짧게 쓰되, 스키마의 모든 키는 반드시 포함하라.\n"
            )
            version_label = "간략"
        else:
            depth_rule = (
                "fact_analysis, narrative_analysis, market_impact_analysis, "
                "investment_scenarios, investment_action_plan, final_assessment "
                "등 스키마의 모든 섹션을 빠짐없이 채워라.\n"
                "각 배열은 가능한 한 3개 항목 이상, 팩트 분석은 뉴스 근거를 "
                "구체적으로 적어라.\n"
            )
            version_label = "심층"
        length_rule = "문자열 필드는 한글 기준 250자 이내로 작성하라.\n"
        return (
            f"{self.base_prompt}\n\n"
            f"위 prompt.md의 투자 리서치 의도를 따르되, 출력은 아래 고정 JSON "
            f"스키마에 맞춘 {version_label} 버전으로 작성하라.\n"
            "마크다운, 표, 코드블록, 설명문은 출력하지 마라.\n"
            "모든 키는 영어 snake_case로만 작성하라.\n"
            f"{depth_rule}"
            f"{length_rule}"
            "불확실한 내용은 '불확실함'이라 한 번만 표기하고, 같은 단어·문장을 반복하지 마라.\n"
            "아래 기준 시각과 요일은 절대 바꾸지 말고 그대로 출력하라.\n\n"
            f"analysis_reference_datetime_kst: {now_kst.isoformat()}\n"
            f"analysis_reference_weekday_kst: {weekday}\n"
            f"query: {query}\n"
            f"searched_days: {searched_days}\n"
            "news_items:\n"
            f"{json.dumps(compact_news, ensure_ascii=False)}"
        )

    def _build_prompt_phase1(
        self,
        query: str,
        searched_days: int,
        compact_news: list[dict[str, Any]],
        *,
        fast: bool = False,
    ) -> str:
        base = self._build_prompt(query, searched_days, compact_news, fast=fast)
        return (
            f"{base}\n\n"
            "[1단계] 이번 응답 JSON 스키마에는 아래 키만 포함하라:\n"
            "analysis_reference_datetime_kst, analysis_reference_weekday_kst, "
            "query, searched_days, keyword_interpretation, news_scan_results, "
            "fact_analysis\n"
            "news_scan_results는 수집된 기사마다 id·headline·summary·sentiment를 "
            "빠짐없이 채워라."
        )

    def _build_prompt_phase2(
        self,
        query: str,
        searched_days: int,
        phase1: dict[str, Any],
        *,
        fast: bool = False,
    ) -> str:
        now_kst = self._get_kst_datetime()
        depth = (
            "각 배열은 2~3개 항목.\n"
            if fast
            else "각 배열은 3개 항목 이상, narrative는 2~3문장.\n"
        )
        context = self._phase_context(query, searched_days, phase1)
        return (
            f"{self.base_prompt}\n\n"
            "[2단계] 아래 1단계 분석 결과를 바탕으로 인사이트 섹션만 JSON으로 작성하라.\n"
            "마크다운, 표, 코드블록, 설명문은 출력하지 마라.\n"
            f"{depth}"
            "문자열 필드는 한글 기준 250자 이내.\n"
            "불확실한 내용은 '불확실함'이라 한 번만 표기하고, 같은 단어·문장을 반복하지 마라.\n\n"
            f"analysis_reference_datetime_kst: {now_kst.isoformat()}\n"
            "phase1_context:\n"
            f"{json.dumps(context, ensure_ascii=False)}\n\n"
            "이번 응답 JSON 스키마 키:\n"
            "market_psychology_analysis, narrative_analysis, market_impact_analysis, "
            "risk_opportunity_matrix, investment_scenarios"
        )

    def _build_prompt_phase3(
        self,
        query: str,
        searched_days: int,
        phase1: dict[str, Any],
        phase2: dict[str, Any],
        *,
        fast: bool = False,
    ) -> str:
        now_kst = self._get_kst_datetime()
        depth = (
            "각 배열은 2~3개 항목.\n"
            if fast
            else "각 배열은 3개 항목 이상.\n"
        )
        context = {
            **self._phase_context(query, searched_days, phase1),
            "investment_scenarios": phase2.get("investment_scenarios"),
            "risk_opportunity_matrix": phase2.get("risk_opportunity_matrix"),
            "narrative_analysis": phase2.get("narrative_analysis"),
        }
        return (
            f"{self.base_prompt}\n\n"
            "[3단계] 아래 분석 맥락을 바탕으로 실행·평가·메타 섹션만 JSON으로 작성하라.\n"
            "마크다운, 표, 코드블록, 설명문은 출력하지 마라.\n"
            f"{depth}"
            "문자열 필드는 한글 기준 250자 이내.\n"
            "불확실한 내용은 '불확실함'이라 한 번만 표기하고, 같은 단어·문장을 반복하지 마라.\n\n"
            f"analysis_completion_datetime_kst: {now_kst.isoformat()}\n"
            "analysis_context:\n"
            f"{json.dumps(context, ensure_ascii=False)}\n\n"
            "이번 응답 JSON 스키마 키:\n"
            "investment_action_plan, final_assessment, "
            "analysis_completion_datetime_kst, reliability_grade, "
            "next_monitoring_date, monitoring_reason"
        )

    @staticmethod
    def _phase_context(
        query: str,
        searched_days: int,
        phase1: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "query": query,
            "searched_days": searched_days,
            "keyword_interpretation": phase1.get("keyword_interpretation"),
            "fact_analysis": phase1.get("fact_analysis"),
            "news_headlines": [
                item.get("headline", "")
                for item in (phase1.get("news_scan_results") or [])
                if isinstance(item, dict)
            ],
        }

    @staticmethod
    def _schema_phase1() -> dict[str, Any]:
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
            },
            "required": [
                "analysis_reference_datetime_kst",
                "analysis_reference_weekday_kst",
                "query",
                "searched_days",
                "keyword_interpretation",
                "news_scan_results",
                "fact_analysis",
            ],
        }

    @staticmethod
    def _schema_phase2() -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "market_psychology_analysis": {
                    "type": "object",
                    "properties": {
                        "fear_greed_index": {"type": "integer"},
                        "summary": {"type": "string"},
                        "biases": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["fear_greed_index", "summary", "biases"],
                },
                "narrative_analysis": {"type": "string", "maxLength": 500},
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
                        "bull_scenario": {"type": "string", "maxLength": 400},
                        "base_scenario": {"type": "string", "maxLength": 400},
                        "bear_scenario": {"type": "string", "maxLength": 400},
                    },
                    "required": [
                        "bull_scenario",
                        "base_scenario",
                        "bear_scenario",
                    ],
                },
            },
            "required": [
                "market_psychology_analysis",
                "narrative_analysis",
                "market_impact_analysis",
                "risk_opportunity_matrix",
                "investment_scenarios",
            ],
        }

    @staticmethod
    def _schema_phase3() -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
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
                "investment_action_plan",
                "final_assessment",
                "analysis_completion_datetime_kst",
                "reliability_grade",
                "next_monitoring_date",
                "monitoring_reason",
            ],
        }

    @staticmethod
    def _has_required(payload: dict[str, Any], keys: list[str]) -> bool:
        for key in keys:
            if key not in payload:
                return False
            value = payload[key]
            if isinstance(value, str) and not value.strip():
                return False
            if isinstance(value, (list, dict)) and not value:
                return False
        return True

    @staticmethod
    def _payload_score(payload: dict[str, Any]) -> int:
        score = len(payload)
        for value in payload.values():
            if isinstance(value, dict) and value:
                score += len(value)
            elif isinstance(value, list) and value:
                score += len(value)
        return score

    @staticmethod
    def _repair_json_text(raw: str) -> str:
        text = raw.strip()
        text = re.sub(r",\s*([}\]])", r"\1", text)
        return text

    @staticmethod
    def _close_truncated_json(raw: str) -> str:
        text = raw.rstrip()
        text = re.sub(r',\s*"[^"]*$', "", text)
        text = re.sub(r",\s*$", "", text)

        stack: list[str] = []
        in_string = False
        escape = False
        for ch in text:
            if escape:
                escape = False
                continue
            if ch == "\\" and in_string:
                escape = True
                continue
            if ch == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch == "{":
                stack.append("}")
            elif ch == "[":
                stack.append("]")
            elif ch in "}]" and stack and stack[-1] == ch:
                stack.pop()

        if in_string:
            text += '"'
        while stack:
            text += stack.pop()
        return text

    @classmethod
    def _parse_json_response(cls, text: str) -> dict[str, Any]:
        raw = (text or "").strip()
        if not raw:
            raise ValueError("LLM 응답이 비어 있습니다.")
        if raw.startswith("```"):
            raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
            raw = re.sub(r"\s*```\s*$", "", raw)

        candidates: list[str] = [raw]
        match = re.search(r"\{[\s\S]*\}", raw)
        if match and match.group(0) != raw:
            candidates.append(match.group(0))
        for variant in list(candidates):
            candidates.append(cls._repair_json_text(variant))
            candidates.append(cls._close_truncated_json(variant))
            candidates.append(cls._close_truncated_json(cls._repair_json_text(variant)))

        seen: set[str] = set()
        last_exc: json.JSONDecodeError | None = None
        best: dict[str, Any] | None = None
        best_score = -1
        for candidate in candidates:
            if candidate in seen:
                continue
            seen.add(candidate)
            try:
                payload = json.loads(candidate)
            except json.JSONDecodeError as exc:
                last_exc = exc
                continue
            if not isinstance(payload, dict):
                raise ValueError("LLM 응답은 JSON 객체 1개여야 합니다.")
            score = cls._payload_score(payload)
            if score > best_score:
                best = payload
                best_score = score

        if best is not None:
            return cls._sanitize_payload(best)

        preview = raw[:500].replace("\n", " ")
        raise ValueError(
            f"LLM JSON 파싱 실패: {last_exc}. 응답 앞부분: {preview}"
        ) from last_exc

    @staticmethod
    def _payload_from_response(response: Any) -> dict[str, Any]:
        parsed = getattr(response, "parsed", None)
        if isinstance(parsed, dict):
            return GeminiNewsAnalyzer._sanitize_payload(parsed)
        text = getattr(response, "text", None) or ""
        return GeminiNewsAnalyzer._parse_json_response(text)

    def _generate_structured(
        self,
        prompt: str,
        schema: dict[str, Any],
        *,
        max_output_tokens: int,
        max_attempts: int = 3,
    ) -> dict[str, Any]:
        required = list(schema.get("required", []))
        last_error: Exception | None = None
        for _attempt in range(max_attempts):
            response = self.client.models.generate_content(
                model=self.settings.vertex_model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_json_schema=schema,
                    max_output_tokens=max_output_tokens,
                ),
            )
            try:
                payload = self._payload_from_response(response)
            except ValueError as exc:
                last_error = exc
                continue
            if required and not self._has_required(payload, required):
                last_error = ValueError(
                    "LLM 응답에 필수 키가 누락되었습니다: "
                    f"{[key for key in required if key not in payload]}"
                )
                continue
            return payload
        if last_error is not None:
            raise last_error
        raise RuntimeError("LLM 분석에 실패했습니다.")

    def analyze(
        self,
        query: str,
        news_items: List[NewsItem],
        searched_days: int,
        *,
        fast: bool = False,
    ) -> dict[str, Any]:
        preview_len = 600 if fast else self.settings.content_preview_length
        compact_news = [
            {
                "published_at": item.published_at.isoformat(),
                "title": item.title,
                "press": item.press,
                "url": item.url,
                "description": item.description,
                "content": item.content[:preview_len],
            }
            for item in news_items
        ]
        tokens_p1 = 4096
        tokens_p2 = 4096 if fast else 5120
        tokens_p3 = 3072

        phase1 = self._generate_structured(
            self._build_prompt_phase1(
                query,
                searched_days,
                compact_news,
                fast=fast,
            ),
            self._schema_phase1(),
            max_output_tokens=tokens_p1,
        )
        phase2 = self._generate_structured(
            self._build_prompt_phase2(
                query,
                searched_days,
                phase1,
                fast=fast,
            ),
            self._schema_phase2(),
            max_output_tokens=tokens_p2,
        )
        phase3 = self._generate_structured(
            self._build_prompt_phase3(
                query,
                searched_days,
                phase1,
                phase2,
                fast=fast,
            ),
            self._schema_phase3(),
            max_output_tokens=tokens_p3,
        )
        merged = {**phase1, **phase2, **phase3}
        if not merged.get("analysis_completion_datetime_kst"):
            merged["analysis_completion_datetime_kst"] = (
                self._get_kst_datetime().isoformat()
            )
        return self._sanitize_payload(merged)
