from __future__ import annotations

from pathlib import Path

from eidolon_sdk.biz.registry.settings import (
    REGISTRY_DB_ENV,
    default_registry_db_path,
    resolve_registry_db_path,
)


def test_registry_defaults_below_host_state_root(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("EIDOLON_STATE_ROOT", str(tmp_path / "state"))
    monkeypatch.delenv(REGISTRY_DB_ENV, raising=False)

    expected = tmp_path / "state/registry/registry.sqlite3"
    assert default_registry_db_path() == expected
    assert resolve_registry_db_path() == expected


def test_registry_explicit_environment_remains_highest_precedence(
    tmp_path: Path, monkeypatch
) -> None:
    configured = tmp_path / "configured.sqlite3"
    monkeypatch.setenv(REGISTRY_DB_ENV, str(configured))

    assert resolve_registry_db_path(tmp_path / "ignored.sqlite3") == configured
