from __future__ import annotations

import pytest
from pydantic import ValidationError

from eidolon_sdk.biz.guard import (
    GuardOwnerFaceProfileApplyResult,
    GuardOwnerFaceProfileManifest,
    GuardOwnerFaceProfileSync,
)
from eidolon_sdk.biz.contracts import (
    CONTROL_OP_GUARD_OWNER_FACE_PROFILE_SYNC,
    VALID_CONTROL_OPS,
)


def _references() -> list[dict[str, object]]:
    return [
        {
            "reference_id": f"ref-{pose}",
            "pose": pose,
            "sha256": str(index) * 64,
            "size_bytes": 1234 + index,
            "content_type": "image/jpeg",
        }
        for index, pose in enumerate(("front", "left", "right"), start=1)
    ]


def test_active_manifest_requires_the_canonical_pose_set() -> None:
    manifest = GuardOwnerFaceProfileManifest.model_validate(
        {
            "schema_v": 1,
            "binding_id": "gb-1",
            "profile_id": "ofp-1",
            "profile_revision": 2,
            "desired_state": "active",
            "model_id": "human_face_feat_mfn_s8_v1",
            "preprocessing_version": "esp-dl-rgb565-be-v1",
            "references": _references(),
        }
    )
    assert len(manifest.references) == 3
    assert {reference.pose for reference in manifest.references} == {"front", "left", "right"}


@pytest.mark.parametrize(
    "patch",
    [
        {"references": _references()[:2]},
        {"references": [*_references(), _references()[0]]},
        {"model_id": None},
        {"raw_image": "forbidden"},
        {"schema_v": 2},
    ],
)
def test_active_manifest_rejects_incomplete_or_sensitive_payloads(
    patch: dict[str, object],
) -> None:
    payload: dict[str, object] = {
        "schema_v": 1,
        "binding_id": "gb-1",
        "profile_id": "ofp-1",
        "profile_revision": 1,
        "desired_state": "active",
        "model_id": "human_face_feat_mfn_s8_v1",
        "preprocessing_version": "esp-dl-rgb565-be-v1",
        "references": _references(),
    }
    payload.update(patch)
    with pytest.raises(ValidationError):
        GuardOwnerFaceProfileManifest.model_validate(payload)


def test_cleared_manifest_and_result_contain_no_biometric_material() -> None:
    manifest = GuardOwnerFaceProfileManifest(
        binding_id="gb-1",
        profile_id="ofp-1",
        profile_revision=3,
        desired_state="cleared",
    )
    result = GuardOwnerFaceProfileApplyResult(
        binding_id="gb-1",
        profile_id="ofp-1",
        profile_revision=3,
        applied_state="cleared",
        template_count=0,
    )
    assert manifest.references == ()
    assert result.template_count == 0


def test_sync_payload_is_strict_and_media_free() -> None:
    sync = GuardOwnerFaceProfileSync(
        binding_id="gb-1",
        profile_id="ofp-1",
        profile_revision=4,
        desired_state="active",
    )
    assert sync.profile_revision == 4
    with pytest.raises(ValidationError):
        GuardOwnerFaceProfileSync.model_validate({**sync.model_dump(), "image_url": "forbidden"})
    assert CONTROL_OP_GUARD_OWNER_FACE_PROFILE_SYNC in VALID_CONTROL_OPS


def test_active_apply_result_requires_at_least_three_templates() -> None:
    with pytest.raises(ValidationError):
        GuardOwnerFaceProfileApplyResult(
            binding_id="gb-1",
            profile_id="ofp-1",
            profile_revision=1,
            applied_state="active",
            model_id="human_face_feat_mfn_s8_v1",
            preprocessing_version="esp-dl-rgb565-be-v1",
            template_count=2,
        )
