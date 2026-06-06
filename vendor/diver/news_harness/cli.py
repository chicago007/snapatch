from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from .config import Settings
from .models import AnalysisResult
from .pipeline import run_pipeline


def _to_dict(result: AnalysisResult | dict[str, Any]) -> dict[str, Any]:
    if isinstance(result, AnalysisResult):
        return result.model_dump()
    return result


def _section_header(title: str) -> list[str]:
    return ["", f"━━━ {title} ━━━"]


def _format_bullets(items: Any) -> list[str]:
    if not isinstance(items, list):
        if items in (None, ""):
            return ["  - (없음)"]
        return [f"  - {items}"]
    if not items:
        return ["  - (없음)"]
    return [f"  - {item}" for item in items]


def _format_keyword_interpretation(data: Any) -> list[str]:
    lines = _section_header("1. 키워드 해석")
    if not isinstance(data, dict) or not data:
        lines.append("  (없음)")
        return lines
    lines.extend(
        [
            f"  분류: {data.get('classification', '')}",
            f"  정의: {data.get('definition', '')}",
            f"  배경: {data.get('background', '')}",
        ],
    )
    return lines


def _format_news_scan_results(items: Any) -> list[str]:
    lines = _section_header("2. 뉴스 스캔")
    if not isinstance(items, list) or not items:
        lines.append("  (수집된 뉴스 없음)")
        return lines
    for item in items:
        if not isinstance(item, dict):
            continue
        lines.extend(
            [
                f"  [{item.get('id', '?')}] {item.get('headline', '')}",
                f"      날짜: {item.get('date', '')}  /  출처: {item.get('source', '')}"
                f"  /  감성: {item.get('sentiment', '')}",
                f"      요약: {item.get('summary', '')}",
            ],
        )
    return lines


def _format_fact_analysis(items: Any) -> list[str]:
    return _section_header("3. 팩트 분석") + _format_bullets(items)


def _format_market_psychology(data: Any) -> list[str]:
    lines = _section_header("4. 시장심리 분석")
    if not isinstance(data, dict) or not data:
        lines.append("  (없음)")
        return lines
    lines.append(f"  공포-탐욕 지수: {data.get('fear_greed_index', '')}")
    summary = data.get("summary", "")
    if summary:
        lines.append(f"  요약: {summary}")
    biases = data.get("biases")
    lines.append("  심리 편향:")
    lines.extend(f"    - {bias}" for bias in (biases or []))
    if not biases:
        lines.append("    - (없음)")
    return lines


def _format_narrative(text: Any) -> list[str]:
    lines = _section_header("5. 내러티브 분석")
    if not text:
        lines.append("  (없음)")
        return lines
    lines.append(f"  {text}")
    return lines


def _format_market_impact(data: Any) -> list[str]:
    lines = _section_header("6. 시장영향 분석")
    if not isinstance(data, dict) or not data:
        lines.append("  (없음)")
        return lines
    lines.append("  직접 영향:")
    lines.extend(
        f"    - {item}" for item in (data.get("direct_impact") or []) or ["(없음)"]
    )
    lines.append("  간접 영향:")
    lines.extend(
        f"    - {item}" for item in (data.get("indirect_impact") or []) or ["(없음)"]
    )
    return lines


def _format_risk_opportunity(data: Any) -> list[str]:
    lines = _section_header("7. 리스크 & 기회 매트릭스")
    if not isinstance(data, dict) or not data:
        lines.append("  (없음)")
        return lines
    sections = [
        ("상승요인", data.get("upside_factors")),
        ("하락요인", data.get("downside_factors")),
        ("블랙스완", data.get("black_swans")),
    ]
    for title, items in sections:
        lines.append(f"  {title}:")
        if items:
            lines.extend(f"    - {item}" for item in items)
        else:
            lines.append("    - (없음)")
    return lines


def _format_scenarios(data: Any) -> list[str]:
    lines = _section_header("8. 투자 시나리오")
    if not isinstance(data, dict) or not data:
        lines.append("  (없음)")
        return lines
    labels = [
        ("bull_scenario", "강세"),
        ("base_scenario", "기본"),
        ("bear_scenario", "약세"),
    ]
    for key, label in labels:
        value = data.get(key, "")
        lines.append(f"  [{label}] {value}")
    return lines


def _format_action_plan(data: Any) -> list[str]:
    lines = _section_header("9. 투자 액션 플랜")
    if not isinstance(data, dict) or not data:
        lines.append("  (없음)")
        return lines
    lines.append(f"  진입: {data.get('entry_timing', '')}")
    lines.append(f"  수익실현: {data.get('profit_taking', '')}")
    lines.append(f"  손절: {data.get('stop_loss', '')}")
    indicators = data.get("monitoring_indicators") or []
    lines.append("  모니터링 지표:")
    if indicators:
        lines.extend(f"    - {item}" for item in indicators)
    else:
        lines.append("    - (없음)")
    return lines


def _format_final_assessment(data: Any) -> list[str]:
    lines = _section_header("10. 최종 평가")
    if not isinstance(data, dict) or not data:
        lines.append("  (없음)")
        return lines
    lines.append(f"  핵심 메시지: {data.get('one_liner_message', '')}")
    strengths = data.get("strengths") or []
    weaknesses = data.get("weaknesses") or []
    lines.append("  강점:")
    if strengths:
        lines.extend(f"    + {item}" for item in strengths)
    else:
        lines.append("    + (없음)")
    lines.append("  약점:")
    if weaknesses:
        lines.extend(f"    - {item}" for item in weaknesses)
    else:
        lines.append("    - (없음)")
    lines.append(f"  최종 권고: {data.get('final_recommendation', '')}")
    return lines


def format_text(result: AnalysisResult | dict[str, Any]) -> str:
    data = _to_dict(result)
    query = data.get("query", "")
    searched_days = data.get("searched_days", "")
    weekday = data.get("analysis_reference_weekday_kst", "")
    ref_dt = data.get("analysis_reference_datetime_kst", "")

    lines: list[str] = [
        f"[{query} 뉴스 분석]",
        f"기준 시각: {ref_dt} ({weekday})",
        f"검색 기간: 최근 {searched_days}일",
    ]
    lines.extend(_format_keyword_interpretation(data.get("keyword_interpretation")))
    lines.extend(_format_news_scan_results(data.get("news_scan_results")))
    lines.extend(_format_fact_analysis(data.get("fact_analysis")))
    lines.extend(_format_market_psychology(data.get("market_psychology_analysis")))
    lines.extend(_format_narrative(data.get("narrative_analysis")))
    lines.extend(_format_market_impact(data.get("market_impact_analysis")))
    lines.extend(_format_risk_opportunity(data.get("risk_opportunity_matrix")))
    lines.extend(_format_scenarios(data.get("investment_scenarios")))
    lines.extend(_format_action_plan(data.get("investment_action_plan")))
    lines.extend(_format_final_assessment(data.get("final_assessment")))

    lines.extend(_section_header("11. 메타"))
    lines.append(
        f"  분석 완료: {data.get('analysis_completion_datetime_kst', '')}",
    )
    lines.append(f"  신뢰도: {data.get('reliability_grade', '')}")
    lines.append(f"  다음 모니터링: {data.get('next_monitoring_date', '')}")
    reason = data.get("monitoring_reason", "")
    if reason:
        lines.append(f"  사유: {reason}")
    return "\n".join(lines)


def print_result(
    result: AnalysisResult | dict[str, Any],
    output_format: str,
) -> None:
    if output_format == "text":
        print(format_text(result))
        return

    payload = _to_dict(result)
    print(json.dumps(payload, ensure_ascii=False))


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    settings = Settings()
    parser = argparse.ArgumentParser(
        description="Naver News + Vertex AI Gemini 분석기",
    )
    parser.add_argument("--query", required=True, help="검색 키워드")
    parser.add_argument(
        "--target-count",
        type=int,
        default=settings.default_target_count,
    )
    parser.add_argument(
        "--max-days",
        type=int,
        default=settings.default_max_days,
    )
    parser.add_argument("--debug", action="store_true")
    parser.add_argument(
        "--skip-content",
        action="store_true",
        default=settings.skip_content,
        help="기사 원문 요청 없이 네이버 요약만 사용",
    )
    parser.add_argument(
        "--fast",
        action="store_true",
        help="빠른 실행 모드(--skip-content와 동일)",
    )
    parser.add_argument(
        "--format",
        choices=["json", "text"],
        default=settings.default_output_format,
        help="출력 형식",
    )
    args = parser.parse_args()

    result = run_pipeline(
        query=args.query,
        target_count=args.target_count,
        max_days=args.max_days,
        debug=args.debug,
        skip_content=args.skip_content or args.fast,
    )

    if args.debug and isinstance(result, tuple):
        analyzed, _ = result
        print_result(analyzed, args.format)
        return

    print_result(result, args.format)


if __name__ == "__main__":
    main()
