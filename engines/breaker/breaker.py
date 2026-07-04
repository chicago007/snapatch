"""주식 시황 속보 생성기 (Vertex AI / Gemini Developer API).

Cursor에서 그대로 실행할 수 있는 단일 파이썬 스크립트.

사용법:
    # 1) API 키 설정 (둘 중 한 가지)
    export GEMINI_API_KEY="AIza..."
    # 또는 .env 파일에 GEMINI_API_KEY=AIza... 작성

    # 2) 의존성 설치
    pip install -r requirements.txt

    # 3) 실행 (snapatch 프로젝트 루트에서)
    python -m hub.cli.breaker              # 기본: once (즉시 1회 생성)
    python -m hub.cli.breaker --print      # once + 콘솔만 출력
    python -m hub.cli.breaker once         # 위와 동일
    python -m hub.cli.breaker loop
    python -m hub.cli.breaker doctor
    python -m hub.cli.breaker --model gemini-2.5-flash

    # 모듈 직접 실행도 가능 (서브커맨드 생략 시 once)
    python -m engines.breaker.breaker
    python -m engines.breaker.breaker --print

옵션:
    --model     사용할 Gemini 모델 (기본: gemini-2.5-pro)
    --sources   매체 목록 콤마 구분으로 덮어쓰기
    --print     파일로 저장하지 않고 콘솔에만 출력
    --once-now  loop 모드에서 시작 직후 1회 즉시 생성

생성된 리포트는 ./outputs/breaker/YYYY-MM-DD_HH-MM_KST.md 로 저장됩니다.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

from .prompt import STOCK_BRIEFING_SYSTEM_PROMPT, build_user_prompt

ENGINE_DIR = Path(__file__).resolve().parent
SNAPATCH_ROOT = ENGINE_DIR.parent.parent


def _load_dotenv_from_project() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    # snapatch 루트 .env 우선 (통합 앱 환경)
    load_dotenv(SNAPATCH_ROOT / ".env", override=True)
    load_dotenv(ENGINE_DIR / ".env", override=False)


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
GEMINI_STREAM_ENDPOINT = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:streamGenerateContent"
)

REPORTS_DIR = SNAPATCH_ROOT / "outputs" / "breaker"

# 일시적 서버 오류 — 지수 백오프로 자동 재시도한다.
TRANSIENT_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
TRANSIENT_MAX_ATTEMPTS = 6
TRANSIENT_BACKOFF_SEC = 2.0
TRANSIENT_BACKOFF_CAP_SEC = 20.0


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


def format_elapsed(seconds: float) -> str:
    """소요 시간을 사람이 읽기 좋은 한국어 문자열로."""
    if seconds < 60:
        return f"{seconds:.1f}초"
    minutes = int(seconds // 60)
    remainder = seconds % 60
    return f"{minutes}분 {remainder:.1f}초"


def now_kst_label(dt: datetime | None = None) -> str:
    """한국시간 'YYYY-MM-DD HH:mm KST' 라벨 생성."""
    if dt is None:
        dt = datetime.now(tz=KST)
    else:
        dt = dt.astimezone(KST)
    return dt.strftime("%Y-%m-%d %H:%M KST")


def _notify(message: str) -> None:
    """진단 메시지를 안전하게 출력.

    Streamlit/Windows 등 일부 실행 환경에서는 sys.stderr 쓰기가
    OSError([Errno 22] 등)를 던질 수 있으므로 모든 예외를 흡수한다.
    """
    try:
        sys.stderr.write(message)
        sys.stderr.flush()
    except Exception:  # noqa: BLE001 - 진단 출력 실패는 무시
        pass


def _post_with_retry(
    url: str,
    headers: dict[str, str],
    body: dict,
    timeout: int,
) -> requests.Response:
    """일시적 오류(429/5xx)와 네트워크 예외에 대해 지수 백오프로 재시도."""
    payload = json.dumps(body)
    last_exc: Exception | None = None

    for attempt in range(1, TRANSIENT_MAX_ATTEMPTS + 1):
        try:
            resp = requests.post(
                url, headers=headers, data=payload, timeout=timeout
            )
        except requests.exceptions.RequestException as exc:
            last_exc = exc
            if attempt >= TRANSIENT_MAX_ATTEMPTS:
                raise RuntimeError(
                    f"Gemini API 요청 실패(네트워크): {exc}"
                ) from exc
            time.sleep(TRANSIENT_BACKOFF_SEC * attempt)
            continue

        if (
            resp.status_code in TRANSIENT_STATUS_CODES
            and attempt < TRANSIENT_MAX_ATTEMPTS
        ):
            wait = _retry_after_seconds(resp) or min(
                TRANSIENT_BACKOFF_SEC * (2 ** (attempt - 1)),
                TRANSIENT_BACKOFF_CAP_SEC,
            )
            _notify(
                f"[retry {attempt}/{TRANSIENT_MAX_ATTEMPTS - 1}] "
                f"Gemini API {resp.status_code} - waiting {wait:.0f}s\n"
            )
            time.sleep(wait)
            continue

        return resp

    # 모든 시도 소진 (네트워크 예외 마지막 케이스 방어)
    if last_exc is not None:
        raise RuntimeError(f"Gemini API 요청 실패: {last_exc}") from last_exc
    return resp


def _retry_after_seconds(resp: requests.Response) -> float | None:
    """Retry-After 헤더(초)가 있으면 파싱해서 반환."""
    value = resp.headers.get("Retry-After")
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        return None


def _build_briefing_body(
    model: str,
    sources: list[str],
    now_kst: str,
    use_google_search: bool,
    max_output_tokens: int,
    temperature: float,
    extra_user_instruction: str | None = None,
) -> dict:
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
        body["tools"] = [{"google_search": {}}]
    return body


def _extract_text_from_response(data: dict) -> str:
    candidate = (data.get("candidates") or [{}])[0]
    parts = (candidate.get("content") or {}).get("parts") or []
    return "\n".join(p.get("text", "") for p in parts if p.get("text"))


def _append_grounding_chunks(text: str, candidate: dict) -> str:
    grounding = candidate.get("groundingMetadata") or {}
    chunks = []
    for chunk in grounding.get("groundingChunks") or []:
        web = chunk.get("web") or {}
        title = web.get("title") or web.get("uri") or ""
        uri = web.get("uri") or ""
        if title and uri:
            chunks.append(f"- [{title}]({uri})")
    if chunks:
        text += "\n\n---\n**검색 근거**\n" + "\n".join(chunks[:8])
    return text


def generate_briefing(
    api_key: str,
    model: str,
    sources: list[str],
    now_kst: str | None = None,
    timeout: int = 120,
    use_google_search: bool = True,
    max_output_tokens: int = 8192,
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

    body = _build_briefing_body(
        model=model,
        sources=sources,
        now_kst=now_kst,
        use_google_search=use_google_search,
        max_output_tokens=max_output_tokens,
        temperature=temperature,
        extra_user_instruction=extra_user_instruction,
    )

    resp = _post_with_retry(url, headers, body, timeout)

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
        elif resp.status_code == 429 or "Quota exceeded" in body_preview:
            hint = (
                "\n\n[안내] Gemini API 할당량(quota)을 초과했습니다. "
                "잠시 후 다시 시도하거나 `.env`의 GEMINI_MODEL을 "
                "`gemini-2.5-flash`로 바꿔 보세요. "
                "사용량: https://ai.dev/rate-limit"
            )
        elif resp.status_code in (500, 502, 503, 504):
            hint = (
                "\n\n[안내] 모델 서버가 일시적으로 과부하 상태입니다(503/UNAVAILABLE). "
                f"자동으로 {TRANSIENT_MAX_ATTEMPTS}회 재시도했지만 실패했습니다. "
                "잠시 후 다시 시도하거나, `.env`의 GEMINI_MODEL을 "
                "`gemini-2.5-flash` 처럼 더 가벼운 모델로 바꿔 보세요."
            )
        raise RuntimeError(f"Gemini API {resp.status_code}: {body_preview}{hint}")

    data = resp.json()
    candidate = (data.get("candidates") or [{}])[0]
    text = _extract_text_from_response(data)
    if not text.strip():
        finish = candidate.get("finishReason")
        if finish == "MAX_TOKENS":
            raise RuntimeError(
                "모델이 본문을 생성하기 전에 출력 토큰 한도에 도달했습니다 "
                "(thinking 토큰이 예산을 소진). max_output_tokens 를 늘리거나 "
                "더 가벼운 설정으로 다시 시도하세요."
            )
        raise RuntimeError(f"빈 응답: {json.dumps(data)[:500]}")

    return _append_grounding_chunks(text, candidate)


def stream_briefing(
    api_key: str,
    model: str,
    sources: list[str],
    now_kst: str | None = None,
    timeout: int = 120,
    use_google_search: bool = True,
    max_output_tokens: int = 8192,
    temperature: float = 0.4,
    extra_user_instruction: str | None = None,
) -> Iterator[str]:
    """Gemini streamGenerateContent 로 리포트를 점진적으로 생성한다."""
    if not api_key:
        raise RuntimeError(
            "API 키가 없습니다. 환경변수 GEMINI_API_KEY 또는 .env에 설정하세요."
        )

    if now_kst is None:
        now_kst = now_kst_label()

    url = f"{GEMINI_STREAM_ENDPOINT.format(model=model)}?alt=sse"
    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": api_key,
    }
    body = _build_briefing_body(
        model=model,
        sources=sources,
        now_kst=now_kst,
        use_google_search=use_google_search,
        max_output_tokens=max_output_tokens,
        temperature=temperature,
        extra_user_instruction=extra_user_instruction,
    )

    resp = requests.post(
        url,
        headers=headers,
        data=json.dumps(body),
        timeout=timeout,
        stream=True,
    )
    if not resp.ok:
        body_preview = resp.text[:500]
        raise RuntimeError(f"Gemini API {resp.status_code}: {body_preview}")

    last_candidate: dict | None = None
    for raw_line in resp.iter_lines(decode_unicode=True):
        if not raw_line or not raw_line.startswith("data: "):
            continue
        payload = raw_line.removeprefix("data: ").strip()
        if not payload or payload == "[DONE]":
            continue
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            continue
        candidate = (data.get("candidates") or [{}])[0]
        last_candidate = candidate
        delta = _extract_text_from_response(data)
        if delta:
            yield delta

    if last_candidate is not None:
        grounding = _append_grounding_chunks("", last_candidate).strip()
        if grounding:
            yield "\n\n" + grounding


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
            "`python breaker.py once` 로 생성을 시도할 수 있습니다.",
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

    started_at = time.perf_counter()
    try:
        content = generate_briefing(api_key, args.model, sources, label)
    except Exception as e:
        print(f"[오류] {e}", file=sys.stderr)
        return 1
    elapsed = time.perf_counter() - started_at

    print(content)

    if not args.print_only:
        path = save_report(content, when)
        print(f"\n[저장] {path}")
    print(f"\n소요 시간: {format_elapsed(elapsed)}")
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
    started_at = time.perf_counter()
    try:
        content = generate_briefing(api_key, model, sources, label)
    except Exception as e:
        print(f"[오류] {e}", file=sys.stderr)
        return
    elapsed = time.perf_counter() - started_at
    print(content)
    path = save_report(content, when)
    print(f"\n[저장] {path}")
    print(f"소요 시간: {format_elapsed(elapsed)}\n")


def parse_sources(raw: str | None) -> list[str]:
    if not raw:
        return list(DEFAULT_SOURCES)
    return [s.strip() for s in raw.split(",") if s.strip()]


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "Vertex AI / Gemini 기반 한국어 시황 속보 생성기 "
            "(서브커맨드 생략 시 once)"
        ),
        epilog=(
            "예: python breaker.py\n"
            "    python breaker.py --print\n"
            "    python breaker.py loop --once-now"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
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
    p.add_argument(
        "--print",
        dest="print_only",
        action="store_true",
        help="once 실행 시 파일 저장 없이 콘솔만 출력 (기본 명령)",
    )

    sub = p.add_subparsers(dest="command", required=False)

    p_once = sub.add_parser(
        "once",
        help="즉시 1회 시황 리포트 생성 (생략 시에도 동일)",
    )
    p_once.add_argument(
        "--print",
        dest="print_only",
        action="store_true",
        help="파일로 저장하지 않고 콘솔에만 출력",
    )
    p_once.set_defaults(func=cmd_once, command="once")

    p_loop = sub.add_parser(
        "loop", help="평일 09~15시 KST 매시 정각 자동 생성 (Ctrl+C로 종료)"
    )
    p_loop.add_argument(
        "--once-now",
        action="store_true",
        help="시작 직후 1회 즉시 생성한 뒤 루프로 진입",
    )
    p_loop.set_defaults(func=cmd_loop, command="loop")

    p_doctor = sub.add_parser(
        "doctor",
        help="GEMINI_API_KEY가 Gemini(Generative Language) API에서 동작하는지 확인",
    )
    p_doctor.set_defaults(func=cmd_doctor, command="doctor")

    p.set_defaults(func=cmd_once, command="once", print_only=False)

    return p


def main() -> int:
    configure_stdio_utf8()
    parser = build_arg_parser()
    args = parser.parse_args()
    if args.command is None:
        args.func = cmd_once
        args.command = "once"
        if not hasattr(args, "print_only"):
            args.print_only = False
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
