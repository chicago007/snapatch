"""주식 시황 속보 생성기 (Vertex AI / Gemini Developer API).

Cursor에서 그대로 실행할 수 있는 단일 파이썬 스크립트.

사용법:
    # 1) API 키 설정 (둘 중 한 가지)
    export GEMINI_API_KEY="AIza..."
    # 또는 .env 파일에 GEMINI_API_KEY=AIza... 작성

    # 2) 의존성 설치
    pip install -r requirements.txt

    # 3) 실행
    python briefing.py once                   # 즉시 1회 생성 → 콘솔 + reports/ 저장
    python briefing.py once --print           # 콘솔에만 출력 (파일 저장 X)
    python briefing.py loop                   # 평일 09~15시 KST 매시 정각 자동 실행
    python briefing.py loop --once-now        # 시작 직후 1회 생성하고 그 뒤 자동 루프
    python briefing.py --model gemini-2.5-flash once

옵션:
    --model     사용할 Gemini 모델 (기본: gemini-2.5-pro)
    --sources   매체 목록 콤마 구분으로 덮어쓰기
    --print     파일로 저장하지 않고 콘솔에만 출력
    --once-now  loop 모드에서 시작 직후 1회 즉시 생성

생성된 리포트는 ./reports/YYYY-MM-DD_HH-MM_KST.md 로 저장됩니다.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

from prompt import STOCK_BRIEFING_SYSTEM_PROMPT, build_user_prompt

PROJECT_ROOT = Path(__file__).resolve().parent


def _load_dotenv_from_project() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    # 프로젝트 .env가 시스템에 잘못된 GEMINI_API_KEY가 있어도 우선 적용되게 함
    load_dotenv(PROJECT_ROOT / ".env", override=True)


_load_dotenv_from_project()


def configure_stdio_utf8() -> None:
    """Windows 기본 콘솔(cp949)에서 이모지 출력 시 UnicodeEncodeError 방지."""
    if sys.platform != "win32":
        return
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8")
        except (OSError, ValueError, AttributeError):
            pass


def get_gemini_api_key() -> str:
    """GEMINI_API_KEY 우선, 없으면 GOOGLE_API_KEY. 따옴표·BOM·CR 정리."""
    raw = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or ""
    cleaned = raw.strip().strip('"').strip("'").lstrip("\ufeff").replace("\r", "")
    return cleaned.strip()

# ---------------------------------------------------------------------------
# 기본 설정
# ---------------------------------------------------------------------------

KST = timezone(timedelta(hours=9))

DEFAULT_SOURCES = [
    "네이버 금융뉴스",
    "구글 금융뉴스",
    "한국경제",
    "연합뉴스",
    "KRX",
    "investing.com",
    "Yahoo Finance",
    "Bloomberg",
    "Reuters",
    "CNBC",
]

GEMINI_ENDPOINT = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)

REPORTS_DIR = Path(__file__).parent / "reports"


@dataclass(frozen=True)
class GeneratePreset:
    model: str
    timeout: int
    max_output_tokens: int
    use_google_search: bool
    temperature: float
    max_retry: int


FAST_PRESET = GeneratePreset(
    model="gemini-2.5-flash",
    timeout=40,
    max_output_tokens=1600,
    use_google_search=False,
    temperature=0.3,
    max_retry=1,
)

ACCURATE_PRESET = GeneratePreset(
    model="gemini-2.5-pro",
    timeout=110,
    max_output_tokens=3000,
    use_google_search=True,
    temperature=0.2,
    max_retry=2,
)


# ---------------------------------------------------------------------------
# 핵심 호출 함수
# ---------------------------------------------------------------------------


def now_kst_label(dt: datetime | None = None) -> str:
    """한국시간 'YYYY-MM-DD HH:mm KST' 라벨 생성."""
    if dt is None:
        dt = datetime.now(tz=KST)
    else:
        dt = dt.astimezone(KST)
    return dt.strftime("%Y-%m-%d %H:%M KST")


def generate_briefing(
    api_key: str,
    model: str,
    sources: list[str],
    now_kst: str | None = None,
    timeout: int = 120,
    use_google_search: bool = True,
    max_output_tokens: int = 4096,
    temperature: float = 0.4,
    extra_user_instruction: str | None = None,
) -> str:
    """Gemini API를 호출해 시황 리포트 마크다운을 반환한다.

    Google Search Grounding을 켜서 최신 뉴스 인용이 가능하도록 한다.
    """
    if not api_key:
        raise RuntimeError(
            "API 키가 없습니다. 환경변수 GEMINI_API_KEY 또는 .env에 설정하세요."
        )

    if now_kst is None:
        now_kst = now_kst_label()

    url = GEMINI_ENDPOINT.format(model=model)
    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": api_key,
    }

    user_prompt = build_user_prompt(now_kst, sources)
    if extra_user_instruction:
        user_prompt = f"{user_prompt}\n\n{extra_user_instruction}"

    body = {
        "systemInstruction": {
            "role": "system",
            "parts": [{"text": STOCK_BRIEFING_SYSTEM_PROMPT}],
        },
        "contents": [
            {
                "role": "user",
                "parts": [{"text": user_prompt}],
            }
        ],
        "generationConfig": {
            "temperature": temperature,
            "topP": 0.9,
            "maxOutputTokens": max_output_tokens,
        },
        "safetySettings": [
            {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
        ],
    }
    if use_google_search:
        # 최신 뉴스를 위해 Google Search Grounding 활성화
        body["tools"] = [{"google_search": {}}]

    resp = requests.post(
        url, headers=headers, data=json.dumps(body), timeout=timeout
    )
    if not resp.ok:
        body_preview = resp.text[:500]
        hint = ""
        if resp.status_code == 400 and (
            "API_KEY_INVALID" in body_preview
            or "API Key not found" in body_preview
        ):
            hint = (
                "\n\n[안내] Google AI Studio에서 발급한 키인지 확인하고 "
                "(https://aistudio.google.com/apikey), "
                "Cloud Console에서 해당 프로젝트에 Generative Language API가 "
                "켜져 있는지·키 제한(HTTP 리퍼러 등)이 서버 요청을 막지 않는지 "
                "확인하세요."
            )
        raise RuntimeError(f"Gemini API {resp.status_code}: {body_preview}{hint}")

    data = resp.json()
    candidate = (data.get("candidates") or [{}])[0]
    parts = (candidate.get("content") or {}).get("parts") or []
    text = "\n".join(p.get("text", "") for p in parts if p.get("text"))
    if not text.strip():
        raise RuntimeError(f"빈 응답: {json.dumps(data)[:500]}")

    # grounding 인용을 본문 끝에 부가
    grounding = candidate.get("groundingMetadata") or {}
    chunks = []
    for c in grounding.get("groundingChunks") or []:
        web = c.get("web") or {}
        title = web.get("title") or web.get("uri") or ""
        uri = web.get("uri") or ""
        if title and uri:
            chunks.append(f"- [{title}]({uri})")
    if chunks:
        text += "\n\n---\n**검색 근거**\n" + "\n".join(chunks[:8])

    return text


def detect_missing_commodities(text: str) -> list[str]:
    missing = []
    if ("WTI" not in text) and ("브렌트" not in text):
        missing.append("원유")
    if "금" not in text:
        missing.append("금")
    if "은" not in text:
        missing.append("은")
    return missing


def build_retry_instruction(missing: list[str]) -> str:
    missing_text = ", ".join(missing)
    return (
        "이전 답변의 마크다운 구조는 유지하되 아래 요구사항을 반드시 반영해 "
        "전체 리포트를 다시 작성해줘.\n"
        f"- 누락된 원자재 항목: {missing_text}\n"
        "- `## 1) 지수 요약` 표에 원자재 행(WTI, 금, 은)을 반드시 포함해줘.\n"
        "- 확인 불가 수치는 추정하지 말고 `—`로 표기해줘."
    )


def generate_with_retry(
    api_key: str,
    preset: GeneratePreset,
    sources: list[str],
    now_kst: str | None = None,
    model_override: str | None = None,
) -> tuple[str, int, list[str]]:
    model = model_override or preset.model
    attempts = 0
    missing: list[str] = []
    extra_instruction: str | None = None

    for attempt in range(1, preset.max_retry + 2):
        attempts = attempt
        text = generate_briefing(
            api_key=api_key,
            model=model,
            sources=sources,
            now_kst=now_kst,
            timeout=preset.timeout,
            use_google_search=preset.use_google_search,
            max_output_tokens=preset.max_output_tokens,
            temperature=preset.temperature,
            extra_user_instruction=extra_instruction,
        )
        missing = detect_missing_commodities(text)
        if not missing:
            return text, attempts, missing
        extra_instruction = build_retry_instruction(missing)
        time.sleep(1.5 * attempt)

    return text, attempts, missing


# ---------------------------------------------------------------------------
# 저장 / 출력
# ---------------------------------------------------------------------------


def save_report(content: str, when: datetime) -> Path:
    REPORTS_DIR.mkdir(exist_ok=True)
    fname = when.astimezone(KST).strftime("%Y-%m-%d_%H-%M_KST.md")
    path = REPORTS_DIR / fname
    path.write_text(content, encoding="utf-8")
    return path


def print_header(label: str) -> None:
    line = "=" * 60
    print(f"\n{line}\n📊 시황 속보 — {label}\n{line}\n")


# ---------------------------------------------------------------------------
# CLI 명령
# ---------------------------------------------------------------------------


def cmd_doctor(_args: argparse.Namespace) -> int:
    """GEMINI_API_KEY가 Generative Language API에서 인식되는지 확인."""
    api_key = get_gemini_api_key()
    if not api_key:
        print(
            "[오류] GEMINI_API_KEY가 비어 있습니다. "
            ".env 또는 환경변수를 확인하세요.",
            file=sys.stderr,
        )
        return 1
    url = "https://generativelanguage.googleapis.com/v1beta/models"
    resp = requests.get(
        url,
        headers={"x-goog-api-key": api_key},
        params={"pageSize": 1},
        timeout=30,
    )
    if resp.ok:
        print(
            "[확인] API 키가 정상입니다. "
            "`python briefing.py once` 로 생성을 시도할 수 있습니다.",
        )
        return 0
    print(
        f"[오류] Google이 이 키를 거부했습니다 ({resp.status_code}).\n"
        f"{resp.text[:600]}",
        file=sys.stderr,
    )
    print(
        "\n[안내] https://aistudio.google.com/apikey 에서 새 키를 만들고 "
        ".env의 GEMINI_API_KEY를 갱신하세요. "
        "Cloud Console에서 프로젝트에 대해 "
        "Generative Language API(generativelanguage.googleapis.com) 사용 설정이 "
        "되어 있는지도 확인하세요.",
        file=sys.stderr,
    )
    return 1


def cmd_once(args: argparse.Namespace) -> int:
    api_key = get_gemini_api_key()
    sources = parse_sources(args.sources)
    when = datetime.now(tz=KST)
    label = now_kst_label(when)

    print_header(label)
    print(f"모델: {args.model}")
    print(f"매체: {', '.join(sources)}\n")
    print("리포트 생성 중… (보통 20~40초 소요)\n")

    try:
        content = generate_briefing(api_key, args.model, sources, label)
    except Exception as e:
        print(f"[오류] {e}", file=sys.stderr)
        return 1

    print(content)

    if not args.print_only:
        path = save_report(content, when)
        print(f"\n[저장] {path}")
    return 0


def cmd_loop(args: argparse.Namespace) -> int:
    """평일 09~15시 KST 매시 정각 자동 실행."""
    api_key = get_gemini_api_key()
    sources = parse_sources(args.sources)

    print(f"[loop] 시작 — 평일 09~15시 KST 매시 정각 자동 생성")
    print(f"       모델: {args.model}")
    print(f"       매체: {', '.join(sources)}")
    print(f"       리포트 저장 위치: {REPORTS_DIR}\n")

    if args.once_now:
        run_one(api_key, args.model, sources, label_override=None)

    last_run_key = ""
    while True:
        try:
            now = datetime.now(tz=KST)
            key = now.strftime("%Y-%m-%d-%H")
            in_window = (
                now.weekday() < 5  # 월(0)~금(4)
                and 9 <= now.hour <= 15
                and now.minute == 0
            )
            if in_window and key != last_run_key:
                last_run_key = key
                run_one(api_key, args.model, sources, label_override=None)
                # 같은 시간대 중복 실행 방지를 위해 다음 분으로 살짝 이동
                time.sleep(65)
                continue

            # 다음 정각까지 남은 초 계산해서 슬립 (최대 60초)
            next_minute = (now + timedelta(minutes=1)).replace(second=0, microsecond=0)
            sleep_sec = max(1, min(60, (next_minute - now).total_seconds()))
            time.sleep(sleep_sec)
        except KeyboardInterrupt:
            print("\n[loop] 종료")
            return 0
        except Exception as e:
            print(f"[loop] 예외: {e}", file=sys.stderr)
            time.sleep(30)


def run_one(
    api_key: str,
    model: str,
    sources: list[str],
    label_override: str | None,
) -> None:
    when = datetime.now(tz=KST)
    label = label_override or now_kst_label(when)
    print_header(label)
    try:
        content = generate_briefing(api_key, model, sources, label)
    except Exception as e:
        print(f"[오류] {e}", file=sys.stderr)
        return
    print(content)
    path = save_report(content, when)
    print(f"\n[저장] {path}\n")


def parse_sources(raw: str | None) -> list[str]:
    if not raw:
        return list(DEFAULT_SOURCES)
    return [s.strip() for s in raw.split(",") if s.strip()]


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Vertex AI / Gemini 기반 한국어 시황 속보 생성기",
    )
    p.add_argument(
        "--model",
        default=os.environ.get("GEMINI_MODEL", "gemini-2.5-pro"),
        help="사용할 Gemini 모델 (기본: gemini-2.5-pro)",
    )
    p.add_argument(
        "--sources",
        default=os.environ.get("BRIEFING_SOURCES"),
        help="매체 목록 콤마 구분 (생략 시 기본 10곳)",
    )

    sub = p.add_subparsers(dest="command", required=True)

    p_once = sub.add_parser("once", help="즉시 1회 시황 리포트 생성")
    p_once.add_argument(
        "--print",
        dest="print_only",
        action="store_true",
        help="파일로 저장하지 않고 콘솔에만 출력",
    )
    p_once.set_defaults(func=cmd_once)

    p_loop = sub.add_parser(
        "loop", help="평일 09~15시 KST 매시 정각 자동 생성 (Ctrl+C로 종료)"
    )
    p_loop.add_argument(
        "--once-now",
        action="store_true",
        help="시작 직후 1회 즉시 생성한 뒤 루프로 진입",
    )
    p_loop.set_defaults(func=cmd_loop)

    p_doctor = sub.add_parser(
        "doctor",
        help="GEMINI_API_KEY가 Gemini(Generative Language) API에서 동작하는지 확인",
    )
    p_doctor.set_defaults(func=cmd_doctor)

    return p


def main() -> int:
    configure_stdio_utf8()
    parser = build_arg_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
