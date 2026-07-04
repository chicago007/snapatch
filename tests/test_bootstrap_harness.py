"""bootstrap 하네스 — 초기화·엔진 패키지 임포트 검증."""

from __future__ import annotations

from hub import bootstrap


def test_init_is_idempotent() -> None:
    bootstrap.init()
    bootstrap.init()
    assert bootstrap.engines_root().name == "engines"


def test_engine_packages_importable() -> None:
    """모든 엔진이 engines.<name> 패키지로 임포트되어야 한다."""
    bootstrap.init()

    from engines.breaker import breaker
    from engines.dejavu import dejavu
    from engines.diver import pipeline
    from engines.match.match import config as match_config

    assert callable(breaker.main)
    assert callable(dejavu.main)
    assert callable(pipeline.run_pipeline)
    assert hasattr(match_config, "FormaConfig")
