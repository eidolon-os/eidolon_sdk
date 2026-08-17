"""SDK's operations contract: an answer of "nothing", kept honest.

SDK runs no service on a Host, so its contract declares nothing. That is only
useful if it stays true. The moment SDK grows a unit, a port, or a database a
product unit opens, silence here would mean Ops backs up and resets a Host
without it — and nothing else in the system would notice.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

_REPOSITORY = Path(__file__).resolve().parents[1]
_CONTRACT = _REPOSITORY / "ops/component.toml"


@pytest.fixture(scope="module")
def contract() -> dict:
    return tomllib.loads(_CONTRACT.read_text(encoding="utf-8"))


def test_the_contract_exists_and_names_this_repository(contract: dict) -> None:
    # The file's whole purpose: Ops distinguishes "declares nothing" from "was
    # never asked", and refuses destructive operations only for the second.
    assert contract["component_id"] == "eidolon_sdk"
    assert contract["schema_version"] == 1


def test_sdk_still_runs_nothing_on_a_host(contract: dict) -> None:
    assert contract.get("units", []) == []
    assert contract.get("ports", {}) == {}
    assert contract.get("inputs", []) == []


def test_sdk_still_holds_no_state_a_host_service_would_open(contract: dict) -> None:
    assert contract.get("state", {}).get("authority", []) == []
    assert contract["reset"]["factory"] == []


def test_no_console_script_here_is_shipped_as_a_unit(contract: dict) -> None:
    project = tomllib.loads((_REPOSITORY / "pyproject.toml").read_text(encoding="utf-8"))
    scripts = project["project"].get("scripts", {})

    # Console scripts are fine — they are tooling, run by a person on a
    # workstation. What would make this contract wrong is one of them appearing
    # in a systemd unit, and that shows up as a unit here first.
    assert contract.get("units", []) == [], (
        f"SDK declares units while shipping scripts {sorted(scripts)}"
    )
