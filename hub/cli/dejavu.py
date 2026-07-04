"""dejavu CLI — capstone001 dejavu.py 터미널 실행 래퍼.

사용법 (프로젝트 루트):
    python -m hub.cli.dejavu
    python -m hub.cli.dejavu engines/dejavu/dejavu.yml
"""

from __future__ import annotations

import sys

from hub import bootstrap

bootstrap.init()

from engines.dejavu import dejavu  # noqa: E402


if __name__ == "__main__":
    dejavu.main(sys.argv[1:])
