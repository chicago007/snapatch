"""breaker CLI — capstone01 breaker.py 터미널 실행 래퍼.

사용법 (프로젝트 루트):
    python -m hub.cli.breaker              # once (기본)
    python -m hub.cli.breaker once --print
    python -m hub.cli.breaker loop --once-now
    python -m hub.cli.breaker doctor
"""

from __future__ import annotations

import sys

from hub import bootstrap

bootstrap.init()

from engines.breaker.breaker import main  # noqa: E402


if __name__ == "__main__":
    sys.exit(main())
