"""bootstrap 하네스 — 엔진 모듈명 충돌 가드 검증."""

from __future__ import annotations

from hub import bootstrap


def test_no_engine_module_collisions() -> None:
    """현재 엔진 구성에 최상위 모듈명 충돌이 없어야 한다."""
    assert bootstrap._detect_module_collisions() == {}


def test_init_is_idempotent() -> None:
    bootstrap.init()
    bootstrap.init()
    assert bootstrap.engines_root().name == "engines"


def test_collision_detected(monkeypatch, tmp_path) -> None:
    """두 엔진이 같은 평면 모듈명을 노출하면 충돌로 잡아낸다."""
    eng_a = tmp_path / "alpha"
    eng_b = tmp_path / "beta"
    eng_a.mkdir()
    eng_b.mkdir()
    (eng_a / "config.py").write_text("X = 1", encoding="utf-8")
    (eng_b / "config.py").write_text("X = 2", encoding="utf-8")

    monkeypatch.setattr(bootstrap, "_ENGINES_ROOT", tmp_path)
    monkeypatch.setattr(bootstrap, "_ENGINE_DIRS", ("alpha", "beta"))

    collisions = bootstrap._detect_module_collisions()
    assert "config" in collisions
    assert set(collisions["config"]) == {"alpha", "beta"}
