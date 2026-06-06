"""breaker CLI — capstone01 breaker.py 터미널 실행 래퍼.

사용법 (프로젝트 루트):
    python -m snapatch.cli.breaker              # once (기본)
    python -m snapatch.cli.breaker once --print
    python -m snapatch.cli.breaker loop --once-now
    python -m snapatch.cli.breaker doctor
"""

from __future__ import annotations

import sys

from snapatch import bootstrap

bootstrap.init()

from breaker import main  # noqa: E402


if __name__ == "__main__":
    sys.exit(main())
