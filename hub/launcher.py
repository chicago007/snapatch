"""snapatch 시작 메뉴 — 웹 UI 또는 터미널 엔진 선택."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent

_ENGINES: tuple[tuple[str, str, str], ...] = (
    (
        "breaker",
        "breaker — 시황 속보",
        "Gemini로 한국어 시황 리포트를 생성합니다. 결과는 outputs/breaker/ 에 저장됩니다.",
    ),
    (
        "diver",
        "diver — 키워드 뉴스 분석",
        "네이버 뉴스를 수집하고 Gemini로 키워드 관련 심층 분석을 합니다. "
        "결과는 outputs/diver/ 에 저장됩니다.",
    ),
    (
        "dejavu",
        "dejavu — 과거 유사 패턴",
        "같은 종목의 과거 유사 구간(6트랙)과 이후 수익률을 분석합니다. "
        "결과는 outputs/dejavu/ 에 저장됩니다.",
    ),
    (
        "match",
        "match — 유사 종목 검색",
        "기준 종목 패턴과 닮은 다른 종목을 SAX 1차 필터 + FastDTW 2차로 찾습니다. "
        "결과는 outputs/match/ 에 저장됩니다.",
    ),
)


def _configure_stdio_utf8() -> None:
    if sys.platform != "win32":
        return
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError, AttributeError):
            pass


def _prompt_choice(prompt: str, valid: set[str]) -> str:
    while True:
        raw = input(prompt).strip()
        if raw in valid:
            return raw
        print(f"  → {', '.join(sorted(valid))} 중에서 입력하세요.\n")


def _print_header() -> None:
    print()
    print("=" * 56)
    print("  snapatch — 주식 속보 · 분석 · 유사도 검색")
    print("=" * 56)
    print()


def _choose_run_mode() -> str:
    print("실행 방식을 선택하세요.\n")
    print("  [1] 웹 UI      Streamlit 대시보드 (breaker / diver / dejavu / match)")
    print("  [2] 터미널 CLI  선택한 기능을 명령줄에서 실행")
    print("  [0] 종료")
    print()
    return _prompt_choice("번호 입력: ", {"0", "1", "2"})


def _choose_engine() -> str | None:
    print("\n터미널에서 실행할 기능을 선택하세요.\n")
    for i, (key, title, desc) in enumerate(_ENGINES, start=1):
        print(f"  [{i}] {title}")
        print(f"      {desc}")
        print()
    print("  [0] 이전 메뉴")
    print()
    valid = {str(i) for i in range(len(_ENGINES) + 1)}
    choice = _prompt_choice("번호 입력: ", valid)
    if choice == "0":
        return None
    return _ENGINES[int(choice) - 1][0]


def _run_streamlit() -> int:
    maingate = _PROJECT_ROOT / "hub" / "ui" / "maingate.py"
    if not maingate.is_file():
        print(f"[오류] {maingate} 를 찾을 수 없습니다.", file=sys.stderr)
        return 1
    print("\n웹 UI를 시작합니다. 브라우저에서 http://localhost:8501 을 여세요.\n")
    return subprocess.run(
        [sys.executable, "-m", "streamlit", "run", str(maingate)],
        cwd=_PROJECT_ROOT,
    ).returncode


def _run_engine_cli(engine: str) -> int:
    cmd: list[str] = [sys.executable, "-m", f"hub.cli.{engine}"]

    if engine == "breaker":
        print()
        print("  생성 모드를 선택하세요.\n")
        print("  [1] 빠름 (flash, 검색 생략, ~5~10초)")
        print("  [2] 정확 (pro, Google 검색, ~20~40초)")
        print()
        mode = _prompt_choice("번호 입력: ", {"1", "2"})
        if mode == "1":
            cmd.append("--fast")

    if engine == "diver":
        print()
        query = input("검색 키워드를 입력하세요: ").strip()
        if not query:
            print("키워드가 비어 있어 취소합니다.")
            return 0
        cmd.extend(["--query", query])

    print()
    return subprocess.run(cmd, cwd=_PROJECT_ROOT).returncode


def main() -> int:
    _configure_stdio_utf8()

    while True:
        _print_header()
        mode = _choose_run_mode()

        if mode == "0":
            print("종료합니다.")
            return 0

        if mode == "1":
            return _run_streamlit()

        while True:
            engine = _choose_engine()
            if engine is None:
                break
            code = _run_engine_cli(engine)
            if code != 0:
                return code
            again = input("\n다른 기능을 실행할까요? (y/N): ").strip().lower()
            if again not in ("y", "yes"):
                return 0
            print()


if __name__ == "__main__":
    raise SystemExit(main())
