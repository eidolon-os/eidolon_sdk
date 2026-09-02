from __future__ import annotations

import importlib.util
import json
import re
import shutil
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
    assert result["commissioning_voucher"] == 1
    assert result["claim_revoke_vectors"] == 1
    assert result["p1_exit_evidence"] == 1


def _rewrite(tmp_path: Path, relative: str, document: dict) -> Path:
    root = tmp_path / "device-foundation-v1"
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(document), encoding="utf-8")
    return root


def test_commissioning_vector_rejects_an_identity_that_was_typed_in(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A registry once let an operator type this value, and one did: a
    Waveshare ESP32-S3-Touch-AMOLED board was admitted as
    "hardware-box3-1cdbd47aef0c" and every later generation of that Claim
    repeated the board type. That registry is gone, but the rule it failed at
    is the one that still matters: only an identity derived from the base
    identity the Hub itself issued may enter the record."""

    runner = _load_runner()
    relative = "golden/commissioning-voucher.json"
    vector = runner.load_json(CONTRACT_ROOT / relative)
    vector["hardware_identity_ref"] = "hardware-box-3-golden"
    monkeypatch.setattr(runner, "ROOT", _rewrite(tmp_path, relative, vector))

    with pytest.raises(runner.ConformanceError, match="identity ref"):
        runner.check_commissioning_voucher()


def test_commissioning_vector_rejects_a_voucher_bound_to_another_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The binding to one operational key is the whole of the voucher's value.

    Without it the voucher is a bearer ticket: anything that reads it once —
    a log line, a screenshot, a proxy — could exchange it for standing under
    somebody else's key."""

    runner = _load_runner()
    relative = "golden/commissioning-voucher.json"
    vector = runner.load_json(CONTRACT_ROOT / relative)
    vector["voucher"]["claims"]["operational_spki_sha256"] = "sha256:" + "0" * 64
    monkeypatch.setattr(runner, "ROOT", _rewrite(tmp_path, relative, vector))

    with pytest.raises(runner.ConformanceError, match="bound to this operational key"):
        runner.check_commissioning_voucher()


def test_rejoin_vector_rejects_an_operator_supplied_hardware_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = _load_runner()
    relative = "state-vectors/hardware-rejoin.json"
    vector = runner.load_json(CONTRACT_ROOT / relative)
    vector["invariants"]["hardware_identity_is_operator_supplied"] = True
    root = tmp_path / "device-foundation-v1"
    shutil.copytree(CONTRACT_ROOT / "state-vectors", root / "state-vectors")
    (root / relative).write_text(json.dumps(vector), encoding="utf-8")
    monkeypatch.setattr(runner, "ROOT", root)

    with pytest.raises(runner.ConformanceError, match="fencing invariant"):
        runner.check_state_vectors()


def test_rejoin_vector_must_carry_the_same_derived_identity_as_the_golden(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = _load_runner()
    relative = "state-vectors/hardware-rejoin.json"
    vector = runner.load_json(CONTRACT_ROOT / relative)
    vector["stable_hardware_identity_ref"] = "hardware-box-3-golden"
    root = tmp_path / "device-foundation-v1"
    shutil.copytree(CONTRACT_ROOT / "state-vectors", root / "state-vectors")
    shutil.copytree(CONTRACT_ROOT / "golden", root / "golden")
    (root / relative).write_text(json.dumps(vector), encoding="utf-8")
    monkeypatch.setattr(runner, "ROOT", root)

    with pytest.raises(runner.ConformanceError, match="derived identity"):
        runner.check_state_vectors()


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
    report = json.loads(result.stdout)
    # The number this capture covers, not the number the workspace happens to
    # hold: a repository added after the freeze is reported, never refused.
    assert report["repository_count"] == 16
    assert isinstance(report["repositories_added_since_capture"], list)


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
    assert report["ok"] is True
    assert report["captured_commits"] is True
    assert report["exact"] is False
    assert report["repository_count"] == 16


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


def test_a_repository_the_capture_named_and_cannot_find_is_still_drift(tmp_path) -> None:
    """The half that must stay red: what the freeze covers has to be there.

    Loosening the added-repository check must not loosen this one — a captured
    participant that has vanished is exactly the drift the gate exists for.
    """

    manifest = json.loads(
        (CONTRACT_ROOT / "baseline" / "cross-repo-heads.v1.json").read_text(encoding="utf-8")
    )
    workspace = tmp_path / "workspace"
    for entry in manifest["repositories"][:-1]:
        repository = workspace / entry["path"]
        (repository / ".git").mkdir(parents=True)

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

    assert result.returncode == 1
    reported = json.loads(result.stderr)
    assert reported["ok"] is False
    assert reported["missing_repositories"] == [manifest["repositories"][-1]["path"]]


def test_a_repository_added_after_the_capture_is_reported_not_refused(tmp_path) -> None:
    manifest = json.loads(
        (CONTRACT_ROOT / "baseline" / "cross-repo-heads.v1.json").read_text(encoding="utf-8")
    )
    workspace = tmp_path / "workspace"
    for entry in manifest["repositories"]:
        (workspace / entry["path"] / ".git").mkdir(parents=True)
    (workspace / "eidolon_something_new" / ".git").mkdir(parents=True)

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
    report = json.loads(result.stdout)
    assert report["repositories_added_since_capture"] == ["eidolon_something_new"]
    assert report["repository_count"] == len(manifest["repositories"])


def test_body_assignment_vocabulary_is_defined_once_and_matches_the_frozen_schema() -> None:
    """The four ways a Body ends up pointing somewhere, and the one mode V1 has.

    Pinned here rather than left to each authority because more than one process
    reads these words: the Kernel writes them, the management surface turns them
    into a sentence, and a phone decides from them whether to say "you cleared
    this" or "the Eidolon it answered as was put away". Two spellings of the
    same fact is how those three come to disagree.

    The mode assertion is against the *frozen* schema, not against a list
    retyped here: ``ReplaceAssignment.mode`` is a ``const`` in the canonical
    document, and a binding that accepted a second mode would be offering a
    short-term takeover the contract deliberately does not define.
    """

    from eidolon_sdk.device_foundation.v1 import (
        AssignmentMode,
        ReplaceAssignment,
        SelectionProvenance,
    )

    assert [item.value for item in SelectionProvenance] == [
        "user_selected",
        "user_cleared",
        "companion_deleted",
        "policy_reconciled",
    ]

    schema = json.loads(
        (CONTRACT_ROOT / "body-mesh" / "schemas.schema.json").read_text(encoding="utf-8")
    )
    frozen_mode = schema["$defs"]["ReplaceAssignment"]["properties"]["mode"]["const"]
    assert [item.value for item in AssignmentMode] == [frozen_mode]

    with pytest.raises(ValueError):
        ReplaceAssignment.model_validate(
            {
                "body_endpoint_id": "voice-body",
                "expected_assignment_revision": 0,
                "companion_ref": "companion_01",
                "mode": "temporary",
                "policy_refs": [],
            }
        )


def test_replacing_an_assignment_needs_no_policy_refs_because_nothing_defines_one() -> None:
    """Empty is the default, and clearing a Body is a first-class request.

    Both halves are load-bearing. No Host in this product defines or evaluates a
    resource policy, so a caller obliged to name refs would be inventing them;
    and ``companion_ref: null`` has to parse, because "nobody answers here" is a
    state an Owner asks for on purpose rather than an absence.
    """

    from eidolon_sdk.device_foundation.v1 import ReplaceAssignment

    cleared = ReplaceAssignment(body_endpoint_id="voice-body", expected_assignment_revision=3)
    assert cleared.companion_ref is None
    assert cleared.policy_refs == ()
    assert cleared.model_dump(mode="json")["policy_refs"] == []
