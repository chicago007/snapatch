"""diver CLI — capstone02 터미널 실행 래퍼.

사용법 (프로젝트 루트):
    python -m snapatch.cli.diver --query 삼성전자
    python -m snapatch.cli.diver --query 삼성전자 --format text --fast
"""

from __future__ import annotations

from snapatch import bootstrap

bootstrap.init()

from diver import main  # noqa: E402


if __name__ == "__main__":
    main()
