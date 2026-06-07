"""match CLI — capstone002 터미널 실행 래퍼.

사용법 (프로젝트 루트):
    python -m hub.cli.match
    python engines/match/match.py
"""

from __future__ import annotations

from hub import bootstrap

bootstrap.init()

from match.main import main  # noqa: E402


if __name__ == "__main__":
    main()
