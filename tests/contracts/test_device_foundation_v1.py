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
    assert result["schemas"] == 9
    assert result["fixtures"] >= 100
    assert result["requirements"] >= 40
    assert result["state_vectors"] == 6
    assert result["development_commissioning_identity"] == 1
    assert result["claim_revoke_vectors"] == 1
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


def test_generated_ph2_bindings_are_sdk_local() -> None:
    config = json.loads((CONTRACT_ROOT / "generation" / "config.json").read_text())
    assert {item["language"] for item in config["binding_outputs"]} == {"python", "dart", "cpp"}
    assert all("repo" not in item for item in config["binding_outputs"])
    for item in config["binding_outputs"]:
        output = CONTRACT_ROOT / item["path"]
        assert output.is_file()
        text = output.read_text(encoding="utf-8")
        assert "accepted_manifest_digest" not in text
        for symbol in (
            "EnrollmentProposal", "DecideEnrollment", "ClaimGrantWireEnvelope",
            "ClaimActivatedEvent", "ClaimRevokedEvent", "ClaimEventPage",
            "EnrollmentProposalPage", "ClaimPage",
        ):
            assert symbol in text


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


def test_every_canonical_model_validates_its_own_wire_form() -> None:
    """A canonical DTO must parse the dictionary its own JSON decodes to.

    Not a style point. Every ASGI framework hands a handler a decoded body, not
    bytes, so a model that only parses in JSON mode cannot be a request body —
    and one that could be constructed and serialized but not read back had
    exactly one symptom on a Host: the Owner's own control plane answered 422 to
    the Local API beside it, and the pending device queue could not be read.

    The examples are the canonical wire forms, so validating them, dumping them,
    and validating that is the whole invariant.
    """

    from pydantic import BaseModel

    import eidolon_sdk.device_foundation.v1 as v1

    models = [
        value
        for value in vars(v1).values()
        if isinstance(value, type)
        and issubclass(value, BaseModel)
        and value.__module__.startswith("eidolon_sdk.device_foundation")
    ]
    assert models, "no canonical bindings were discovered"

    checked: list[str] = []
    failures: list[str] = []
    for path in sorted((CONTRACT_ROOT / "examples" / "valid").glob("*.json")):
        for case in json.loads(path.read_text(encoding="utf-8")).get("cases", []):
            value = case.get("value")
            if not isinstance(value, dict):
                continue
            for model in models:
                try:
                    parsed = model.model_validate(value)
                except Exception:
                    continue
                checked.append(f"{model.__name__}:{case.get('case_id')}")
                try:
                    model.model_validate(parsed.model_dump(mode="json"))
                except Exception as exc:
                    failures.append(f"{model.__name__} ({case.get('case_id')}): {exc}")

    assert not failures, "canonical models rejected their own wire form:\n" + "\n".join(failures)
    # Every canonical example is a wire form some binding must accept. A case
    # no model can parse is the same defect wearing the other hat.
    assert len(checked) >= 50


def test_a_canonical_enum_still_refuses_a_value_it_does_not_define() -> None:
    from eidolon_sdk.device_foundation.v1 import ClaimQuery, ClaimState

    query = ClaimQuery(
        owner_domain_id="owner-domain_01",
        states=(ClaimState.ACTIVE,),
        cursor=None,
        limit=50,
    )
    assert ClaimQuery.model_validate(query.model_dump(mode="json")) == query
    with pytest.raises(ValueError):
        ClaimQuery.model_validate(
            {
                "owner_domain_id": "owner-domain_01",
                "states": ["not-a-claim-state"],
                "cursor": None,
                "limit": 50,
            }
        )
