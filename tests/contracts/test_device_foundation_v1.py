from __future__ import annotations

import importlib.util
import json
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
    assert result["schemas"] == 6
    assert result["fixtures"] >= 40
    assert result["requirements"] >= 15
    assert result["state_vectors"] == 3


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
    roots = [
        path
        for path in workspace.rglob("device_foundation/v1")
        if path.is_dir()
        and ".git" not in path.parts
        and ".worktrees" not in path.parts
        and ".migration-backups" not in path.parts
    ]
    assert roots == [CONTRACT_ROOT]


def test_duplicate_json_keys_are_rejected(tmp_path: Path) -> None:
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text('{"id":"first","id":"second"}', encoding="utf-8")
    runner = _load_runner()
    with pytest.raises(runner.ConformanceError, match="duplicate JSON key"):
        runner.load_json(duplicate)
