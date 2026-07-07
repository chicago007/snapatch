from __future__ import annotations

import json
from types import SimpleNamespace

from engines.diver.gemini_analyzer import GeminiNewsAnalyzer


def test_parse_response_json_uses_parsed_attribute():
    payload = {"query": "삼성전자", "searched_days": 30}
    response = SimpleNamespace(parsed=payload, text='{"ignored": true}')
    assert GeminiNewsAnalyzer._parse_response_json(response) == payload


def test_parse_response_json_strips_markdown_fence():
    payload = {"query": "테스트"}
    response = SimpleNamespace(
        parsed=None,
        text="```json\n" + json.dumps(payload, ensure_ascii=False) + "\n```",
    )
    assert GeminiNewsAnalyzer._parse_response_json(response) == payload


def test_response_truncated_detects_max_tokens():
    response = SimpleNamespace(
        candidates=[SimpleNamespace(finish_reason="MAX_TOKENS")],
    )
    assert GeminiNewsAnalyzer._response_truncated(response) is True


def test_sanitize_payload_collapses_repeated_uncertainty():
    data = {
        "narrative_analysis": "불확실함. 불확실함. 불확실함. 내용",
        "fact_analysis": ["a" * 600],
    }
    cleaned = GeminiNewsAnalyzer._sanitize_payload(data)
    assert cleaned["narrative_analysis"].count("불확실함") == 1
    assert len(cleaned["fact_analysis"][0]) <= 501


def test_parse_response_json_rejects_non_object():
    response = SimpleNamespace(parsed=None, text='["not", "object"]')
    try:
        GeminiNewsAnalyzer._parse_response_json(response)
    except ValueError as exc:
        assert "JSON 객체" in str(exc)
    else:
        raise AssertionError("expected ValueError")
