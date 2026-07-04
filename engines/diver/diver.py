from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .config import Settings, diver_output_dir
from .models import AnalysisResult
from .pipeline import run_pipeline

KST = timezone(timedelta(hours=9))


def _safe_slug(query: str, max_len: int = 32) -> str:
    slug = re.sub(r"[^\w가-힣]+", "_", query.strip(), flags=re.UNICODE)
    slug = slug.strip("_")
    return slug[:max_len] if slug else "query"


@dataclass(frozen=True)
class SavedReports:
    md_path: Path


def save_result_files(
    result: AnalysisResult | dict[str, Any],
    query: str,
    when: datetime | None = None,
) -> SavedReports:
    """분석 결과를 outputs/diver/ 에 Markdown 으로 저장."""
    when = when or datetime.now(tz=KST)
    slug = _safe_slug(query)
    tag = when.astimezone(KST).strftime("%Y-%m-%d_%H-%M_KST")
    md_path = (diver_output_dir() / f"{slug}_{tag}").with_suffix(".md")
    md_path.write_text(format_md(result), encoding="utf-8")
    return SavedReports(md_path=md_path)


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


def _md_bullets(items: Any, empty: str = "(없음)") -> list[str]:
    if not isinstance(items, list):
        if items in (None, ""):
            return [f"- {empty}"]
        return [f"- {items}"]
    if not items:
        return [f"- {empty}"]
    return [f"- {item}" for item in items]


def format_md(result: AnalysisResult | dict[str, Any]) -> str:
    """분석 결과를 Markdown 문서 문자열로 변환."""
    data = _to_dict(result)
    query = data.get("query", "")
    searched_days = data.get("searched_days", "")
    weekday = data.get("analysis_reference_weekday_kst", "")
    ref_dt = data.get("analysis_reference_datetime_kst", "")

    md: list[str] = [
        f"# {query} 뉴스 분석",
        "",
        f"- **기준 시각**: {ref_dt} ({weekday})",
        f"- **검색 기간**: 최근 {searched_days}일",
    ]

    ki = data.get("keyword_interpretation") or {}
    md += ["", "## 1. 키워드 해석"]
    if ki:
        md += [
            f"- **분류**: {ki.get('classification', '')}",
            f"- **정의**: {ki.get('definition', '')}",
            f"- **배경**: {ki.get('background', '')}",
        ]
    else:
        md += ["- (없음)"]

    md += ["", "## 2. 뉴스 스캔"]
    news = data.get("news_scan_results")
    if isinstance(news, list) and news:
        for item in news:
            if not isinstance(item, dict):
                continue
            md += [
                f"### [{item.get('id', '?')}] {item.get('headline', '')}",
                f"- 날짜: {item.get('date', '')} · 출처: {item.get('source', '')}"
                f" · 감성: {item.get('sentiment', '')}",
                f"- 요약: {item.get('summary', '')}",
                "",
            ]
    else:
        md += ["(수집된 뉴스 없음)"]

    md += ["", "## 3. 팩트 분석"] + _md_bullets(data.get("fact_analysis"))

    mp = data.get("market_psychology_analysis") or {}
    md += ["", "## 4. 시장심리 분석"]
    if mp:
        md += [f"- **공포-탐욕 지수**: {mp.get('fear_greed_index', '')}"]
        if mp.get("summary"):
            md += [f"- **요약**: {mp.get('summary')}"]
        md += ["- **심리 편향**:"]
        md += [f"  - {b}" for b in (mp.get("biases") or ["(없음)"])]
    else:
        md += ["- (없음)"]

    md += [
        "",
        "## 5. 내러티브 분석",
        str(data.get("narrative_analysis") or "(없음)"),
    ]

    mi = data.get("market_impact_analysis") or {}
    md += ["", "## 6. 시장영향 분석"]
    if mi:
        md += ["**직접 영향**"] + _md_bullets(mi.get("direct_impact"))
        md += ["", "**간접 영향**"] + _md_bullets(mi.get("indirect_impact"))
    else:
        md += ["- (없음)"]

    ro = data.get("risk_opportunity_matrix") or {}
    md += ["", "## 7. 리스크 & 기회 매트릭스"]
    if ro:
        for title, key in (
            ("상승요인", "upside_factors"),
            ("하락요인", "downside_factors"),
            ("블랙스완", "black_swans"),
        ):
            md += [f"**{title}**"] + _md_bullets(ro.get(key)) + [""]
    else:
        md += ["- (없음)"]

    sc = data.get("investment_scenarios") or {}
    md += ["", "## 8. 투자 시나리오"]
    if sc:
        md += [
            f"- **강세**: {sc.get('bull_scenario', '')}",
            f"- **기본**: {sc.get('base_scenario', '')}",
            f"- **약세**: {sc.get('bear_scenario', '')}",
        ]
    else:
        md += ["- (없음)"]

    ap = data.get("investment_action_plan") or {}
    md += ["", "## 9. 투자 액션 플랜"]
    if ap:
        md += [
            f"- **진입**: {ap.get('entry_timing', '')}",
            f"- **수익실현**: {ap.get('profit_taking', '')}",
            f"- **손절**: {ap.get('stop_loss', '')}",
            "- **모니터링 지표**:",
        ]
        md += [f"  - {i}" for i in (ap.get("monitoring_indicators") or ["(없음)"])]
    else:
        md += ["- (없음)"]

    fa = data.get("final_assessment") or {}
    md += ["", "## 10. 최종 평가"]
    if fa:
        md += [f"- **핵심 메시지**: {fa.get('one_liner_message', '')}", "", "**강점**"]
        md += [f"- {i}" for i in (fa.get("strengths") or ["(없음)"])]
        md += ["", "**약점**"]
        md += [f"- {i}" for i in (fa.get("weaknesses") or ["(없음)"])]
        md += ["", f"- **최종 권고**: {fa.get('final_recommendation', '')}"]
    else:
        md += ["- (없음)"]

    md += [
        "",
        "## 11. 메타",
        f"- 분석 완료: {data.get('analysis_completion_datetime_kst', '')}",
        f"- 신뢰도: {data.get('reliability_grade', '')}",
        f"- 다음 모니터링: {data.get('next_monitoring_date', '')}",
    ]
    if data.get("monitoring_reason"):
        md += [f"- 사유: {data.get('monitoring_reason')}"]

    return "\n".join(md)


def _format_elapsed(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.1f}초"
    minutes = int(seconds // 60)
    remainder = seconds % 60
    return f"{minutes}분 {remainder:.1f}초"


def print_elapsed(seconds: float, output_format: str) -> None:
    label = _format_elapsed(seconds)
    if output_format == "text":
        print(f"\n━━━ 실행 정보 ━━━\n  소요 시간: {label}")
        return
    print(
        json.dumps(
            {"elapsed_seconds": round(seconds, 2), "elapsed_display": label},
            ensure_ascii=False,
        ),
    )


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
        help="원문 생략 (--skip-content 와 동일)",
    )
    parser.add_argument(
        "--format",
        choices=["json", "text"],
        default=settings.default_output_format,
        help="출력 형식",
    )
    parser.add_argument(
        "--no-save",
        action="store_true",
        help="outputs/diver/ 에 파일 저장하지 않음",
    )
    args = parser.parse_args()

    started_at = time.perf_counter()
    result = run_pipeline(
        query=args.query,
        target_count=args.target_count,
        max_days=args.max_days,
        debug=args.debug,
        skip_content=args.skip_content or args.fast,
    )
    elapsed = time.perf_counter() - started_at

    if args.debug and isinstance(result, tuple):
        analyzed, _ = result
        print_result(analyzed, args.format)
        print_elapsed(elapsed, args.format)
        if not args.no_save:
            saved = save_result_files(analyzed, args.query)
            print(f"\n[저장] {saved.md_path}")
        return

    print_result(result, args.format)
    print_elapsed(elapsed, args.format)
    if not args.no_save:
        saved = save_result_files(result, args.query)
        print(f"\n[저장] {saved.md_path}")


if __name__ == "__main__":
    main()
