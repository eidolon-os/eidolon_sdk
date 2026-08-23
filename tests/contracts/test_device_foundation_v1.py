from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest


SDK_ROOT = Path(__file__).resolve().parents[2]
CONTRACT_ROOT = SDK_ROOT / "contracts" / "device_foundation" / "v1"


def _load_runner():
    path = CONTRACT_ROOT / "conformance" / "run.py"
    spec = importlib.util.spec_from_file_location("device_foundation_v1_conformance", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_conformance_runner_passes() -> None:
    result = _load_runner().run()
    assert result["schemas"] == 7
    assert result["fixtures"] >= 60
    assert result["requirements"] >= 40
    assert result["state_vectors"] == 4
    assert result["p1_exit_evidence"] == 1


def test_p1_exit_evidence_fails_if_host_move_reenters_commissioning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = _load_runner()
    evidence = runner.load_json(CONTRACT_ROOT / "evidence" / "p1-host-independence.json")
    evidence["device"]["entered_commissioning_during_authority_move"] = True
    evidence_root = tmp_path / "device-foundation-v1"
    (evidence_root / "evidence").mkdir(parents=True)
    (evidence_root / "evidence" / "p1-host-independence.json").write_text(
        json.dumps(evidence), encoding="utf-8"
    )
    monkeypatch.setattr(runner, "ROOT", evidence_root)

    with pytest.raises(runner.ConformanceError, match="commissioning"):
        runner.check_p1_exit_evidence()


def test_p1_exit_evidence_fails_if_host_runtime_contains_owner_private_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = _load_runner()
    evidence = runner.load_json(CONTRACT_ROOT / "evidence" / "p1-host-independence.json")
    evidence["owner_identity"]["runtime_contains_directory_signing_private_key"] = True
    evidence_root = tmp_path / "device-foundation-v1"
    (evidence_root / "evidence").mkdir(parents=True)
    (evidence_root / "evidence" / "p1-host-independence.json").write_text(
        json.dumps(evidence), encoding="utf-8"
    )
    monkeypatch.setattr(runner, "ROOT", evidence_root)

    with pytest.raises(runner.ConformanceError, match="private key"):
        runner.check_p1_exit_evidence()


def test_generation_is_clean() -> None:
    result = subprocess.run(
        [sys.executable, str(CONTRACT_ROOT / "generation" / "generate.py"), "--check"],
        cwd=SDK_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_baseline_repository_set_matches_workspace() -> None:
    workspace = SDK_ROOT.parent
    result = subprocess.run(
        [
            sys.executable,
            str(CONTRACT_ROOT / "baseline" / "verify.py"),
            "--workspace-root",
            str(workspace),
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["repository_count"] == 16


def test_p1_release_input_commits_and_tree_digests_are_reproducible() -> None:
    workspace = SDK_ROOT.parent
    result = subprocess.run(
        [
            sys.executable,
            str(CONTRACT_ROOT / "baseline" / "verify.py"),
            "--manifest",
            str(CONTRACT_ROOT / "baseline" / "p1-release-inputs.v1.json"),
            "--workspace-root",
            str(workspace),
            "--captured-commits",
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report == {
        "captured_commits": True,
        "exact": False,
        "ok": True,
        "repository_count": 16,
    }


def test_baseline_rejects_repository_set_drift(tmp_path: Path) -> None:
    (tmp_path / "unexpected" / ".git").mkdir(parents=True)
    result = subprocess.run(
        [
            sys.executable,
            str(CONTRACT_ROOT / "baseline" / "verify.py"),
            "--workspace-root",
            str(tmp_path),
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 1
    failure = json.loads(result.stderr)
    assert failure["added_repositories"] == ["unexpected"]
    assert "docs" in failure["missing_repositories"]


def test_canonical_source_is_unique() -> None:
    workspace = SDK_ROOT.parent
    # Runtime bindings intentionally share the package namespace, but only the
    # contracts tree may contain normative schemas, requirements, or profiles.
    markers = (
        Path("common/schemas.schema.json"),
        Path("requirements/requirements.json"),
        Path("profile/eidolon-trust-p256-hpke-v1.json"),
    )
    for marker in markers:
        matches = [
            path
            for path in workspace.rglob(marker.name)
            if path.as_posix().endswith(f"device_foundation/v1/{marker.as_posix()}")
            and ".git" not in path.parts
            and ".worktrees" not in path.parts
            and ".migration-backups" not in path.parts
        ]
        assert matches == [CONTRACT_ROOT / marker]


def test_p1_owner_directory_consumers_do_not_persist_host_identity() -> None:
    workspace = SDK_ROOT.parent
    source_roots = (
        workspace / "eidolon-client-esp32" / "main" / "eidolon" / "authority_locator.cc",
        workspace / "eidolon-client-esp32" / "main" / "eidolon" / "authority_locator_core.cc",
        workspace / "eidolon_client_mobile" / "lib" / "src" / "features" / "device_setup",
        workspace / "eidolon_hub" / "hub" / "adapters" / "security" / "owner_directory.py",
        workspace / "eidolon_admin" / "server" / "eidolon_admin_server" / "local_api" / "config.py",
    )
    forbidden = re.compile(r"\b(?:host_id|hub_host|server_ip|room_name)\b")
    matches: list[str] = []
    for root in source_roots:
        paths = [root] if root.is_file() else [path for path in root.rglob("*") if path.is_file()]
        for path in paths:
            if path.suffix not in {".cc", ".dart", ".py"}:
                continue
            for line_number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), start=1
            ):
                if forbidden.search(line):
                    matches.append(f"{path.relative_to(workspace)}:{line_number}:{line.strip()}")
    assert matches == [], "Host-bound identity leaked into Owner directory consumer:\n" + "\n".join(
        matches
    )


def test_duplicate_json_keys_are_rejected(tmp_path: Path) -> None:
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text('{"id":"first","id":"second"}', encoding="utf-8")
    runner = _load_runner()
    with pytest.raises(runner.ConformanceError, match="duplicate JSON key"):
        runner.load_json(duplicate)
