"""engines 소스 경로와 환경변수(.env)를 한 번만 초기화한다.

각 캡스톤 원본 코드는 `engines/<feature>/` 에 그대로 보존되어 있고,
최상위 모듈 이름(`breaker`, `config`, `pipeline`, `dejavu`, `match`)으로
import 할 수 있도록 sys.path 에 등록한다.
"""

from __future__ import annotations

import sys
from pathlib import Path

from hub.paths import (
    breaker_output_dir,
    dejavu_output_dir,
    diver_output_dir,
    match_output_dir,
    outputs_dir,
    project_root,
)

_PROJECT_ROOT = project_root()
_ENGINES_ROOT = _PROJECT_ROOT / "engines"

_ENGINE_DIRS = ("breaker", "diver", "dejavu", "match")

_initialized = False


def engines_root() -> Path:
    return _ENGINES_ROOT


def _top_level_modules(engine_dir: Path) -> set[str]:
    """엔진 디렉터리에서 `import <이름>` 으로 노출되는 최상위 모듈명 집합."""
    names: set[str] = set()
    if not engine_dir.is_dir():
        return names
    for entry in engine_dir.iterdir():
        if entry.name.startswith((".", "_")):
            continue
        if entry.suffix == ".py":
            names.add(entry.stem)
        elif entry.is_dir() and (entry / "__init__.py").is_file():
            names.add(entry.name)
    return names


def _detect_module_collisions() -> dict[str, list[str]]:
    """여러 엔진이 같은 최상위 모듈명을 노출하는지 검사.

    모든 엔진 디렉터리가 동시에 sys.path 에 올라가므로, 서로 다른 엔진이
    같은 평면 이름(`config`, `models`, `prompt` 등)을 쓰면 먼저 import 된
    쪽이 다른 쪽을 조용히 가린다. 이를 startup 시점에 잡아낸다.
    """
    owners: dict[str, list[str]] = {}
    for name in _ENGINE_DIRS:
        for mod in _top_level_modules(_ENGINES_ROOT / name):
            owners.setdefault(mod, []).append(name)
    return {mod: eng for mod, eng in owners.items() if len(eng) > 1}


def init() -> None:
    """engines 경로 등록 + .env 로드 (idempotent).

    등록 전에 엔진 간 최상위 모듈명 충돌을 검사해, 조용한 shadowing 대신
    명확한 오류로 즉시 실패한다.
    """
    global _initialized
    if _initialized:
        return

    collisions = _detect_module_collisions()
    if collisions:
        detail = "; ".join(
            f"'{mod}' ← {', '.join(engs)}" for mod, engs in sorted(collisions.items())
        )
        raise RuntimeError(
            "엔진 간 최상위 모듈명 충돌이 감지되었습니다. "
            "서로 다른 엔진이 같은 이름을 쓰면 import 가 조용히 덮어써집니다. "
            "해당 모듈을 패키지(예: match 처럼)로 감싸거나 이름을 바꾸세요: "
            f"{detail}"
        )

    for name in _ENGINE_DIRS:
        path = _ENGINES_ROOT / name
        if path.is_dir():
            str_path = str(path)
            if str_path not in sys.path:
                sys.path.insert(0, str_path)

    try:
        from dotenv import load_dotenv

        load_dotenv(_PROJECT_ROOT / ".env")
    except ImportError:
        pass

    _initialized = True
