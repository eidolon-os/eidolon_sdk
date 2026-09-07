#!/usr/bin/env python3
"""Regenerate the Device Control configuration response golden.

The answer a Body gets when it asks what it should be. Three implementations
parse it — the firmware, the phone, and whatever reads it next — against one
producer, and none of them shared a definition.

The three accepted cases exist because of a specific confusion this contract
should not leave to prose: `lifecycle_state` and the presence of a channel are
separate facts, and "approved with no channel yet" is a real, expected state
rather than an error or a revocation. `纯软件Body准入方案.md` §4.3 records the
product already blurring exactly that distinction, so the vector states what a
Body must conclude in each case rather than leaving each parser to decide.

The active case carries the real binding this corpus already publishes, so the
outer object and the inner document move together.
"""

from __future__ import annotations

import hashlib
import json

import rfc8785

from _vector_helpers import ROOT, save

REQUEST_NONCE = "Y29uZmlndXJhdGlvbi1ub25jZQ"
DEVICE_REF = {
    "device_instance_id":
        "device-instance-591d7c62d0bc738376935f77ff2acd5472bbee64207a765df03af6d6240c07dc",
    "owner_domain_id": "owner-domain_01",
    "owner_domain_generation": 3,
    "claim_generation": 7,
    "trust_epoch": 4,
}
MANIFEST_REF = {
    "manifest_id": "manifest_01",
    "revision": 1,
    "digest": "sha256:31f7d2a97fd3f1980db53c81a0a724cf1451109d9600d99009966301bea64bcc",
}


def session_binding() -> dict:
    """The channel entry, carrying the binding golden/livekit-session-binding.json pins."""

    inner = json.loads(
        (ROOT / "golden" / "livekit-session-binding.json").read_text(encoding="utf-8")
    )
    return {
        "channel_id": "chan-0f3a91c4d25b47e8a603",
        "purpose": "device-session",
        "kinds": ["audio"],
        "binding_format": inner["binding_format"],
        "issued_at_ms": 1788000000000,
        "expires_at_ms": 1788001800000,
        "opaque_binding": inner["opaque_binding"],
    }


def response(*, lifecycle_state: str, channels: list, manifest: dict | None) -> dict:
    value = {
        "operation": "device-control.configuration",
        "nonce": REQUEST_NONCE,
        "device_ref": DEVICE_REF,
        "lifecycle_state": lifecycle_state,
        "channels": channels,
    }
    if manifest is not None:
        value["manifest"] = manifest
    return value


def case(case_id: str, body_state: str, why: str, value: dict) -> dict:
    canonical = rfc8785.dumps(value)
    return {
        "case_id": case_id,
        "body_state": body_state,
        "why": why,
        "response": value,
        "canonical_utf8": canonical.decode("utf-8"),
        "canonical_sha256": "sha256:" + hashlib.sha256(canonical).hexdigest(),
    }


def main() -> None:
    binding = session_binding()
    vector = {
        "vector_id": "DF-DEVICE-CONTROL-CONFIGURATION-RESPONSE-001",
        "description": (
            "What `configuration:pull` answers, and what a Body must conclude from each "
            "answer. The outer object had no contract while four implementations read or "
            "wrote it; `body_state` is here because `lifecycle_state` and the presence of a "
            "channel are separate facts, and reading approved-with-no-channel as a failure "
            "is a Body giving up on an enrolment that is fine."
        ),
        "schema": (
            "https://contracts.eidolon.live/device-foundation/v1/device-control/"
            "schemas.schema.json#/$defs/DeviceConfigurationResult"
        ),
        # Named because the vector could not say it, and two reasonable Bodies
        # read it differently. A reader must not refuse a channel because its
        # own clock says the grant has expired: a device that has not reached
        # NTP yet — the normal state at boot — would refuse a channel that is
        # fine, which is a worse failure than the one the check prevents. What
        # is refusable at parse time is a grant that is not internally coherent,
        # which is what the `expires_at_ms: 0` refusal case below is.
        #
        # The accepted cases are therefore deliberately in the past. A consumer
        # that judges expiry against the wall clock fails this vector instead of
        # passing it, the same way the session binding's padding separates the
        # two base64 alphabets.
        "expiry_is_not_judged_against": "the reader's clock",
        "request_nonce": REQUEST_NONCE,
        "device_ref": DEVICE_REF,
        "body_states": ["active", "awaiting-channel", "revoked"],
        "cases": [
            case(
                "DF-DEVICE-CONTROL-CONFIGURATION-ACTIVE",
                "active",
                "A Claim the Authority holds and a channel the Channel has answered for.",
                response(lifecycle_state="approved", channels=[binding], manifest=MANIFEST_REF),
            ),
            case(
                "DF-DEVICE-CONTROL-CONFIGURATION-APPROVED-AWAITING-CHANNEL",
                "awaiting-channel",
                (
                    "Approved, and no channel yet. Not an error and not a revocation: the "
                    "Authority holds the Claim and the Channel has not answered. A Body that "
                    "treats this as failure abandons an enrolment that is fine, and one that "
                    "treats it as active joins a room that does not exist."
                ),
                response(lifecycle_state="approved", channels=[], manifest=MANIFEST_REF),
            ),
            case(
                "DF-DEVICE-CONTROL-CONFIGURATION-REVOKED",
                "revoked",
                (
                    "Terminal. The absence of a channel here means something different from "
                    "the case above, which is the whole reason both are in this vector."
                ),
                response(lifecycle_state="revoked", channels=[], manifest=None),
            ),
        ],
        "must_refuse": [
            {
                "case_id": "DF-DEVICE-CONTROL-CONFIGURATION-WRONG-OPERATION",
                "why": "An answer to another question is not an answer to this one.",
                "response": {
                    **response(lifecycle_state="approved", channels=[], manifest=None),
                    "operation": "device-control.manifest-assert",
                },
            },
            {
                "case_id": "DF-DEVICE-CONTROL-CONFIGURATION-UNKNOWN-LIFECYCLE",
                "why": (
                    "A state this vocabulary does not define. Guessing which of the two it "
                    "resembles is how a Body grants itself voice on an unknown status."
                ),
                "response": {
                    **response(lifecycle_state="approved", channels=[], manifest=None),
                    "lifecycle_state": "pending",
                },
            },
            {
                "case_id": "DF-DEVICE-CONTROL-CONFIGURATION-CHANNEL-ALREADY-EXPIRED",
                "why": (
                    "A grant with no life left is not a grant. Accepting it spends the "
                    "reconnect budget on a room that will refuse the token."
                ),
                "response": response(
                    lifecycle_state="approved",
                    channels=[{**binding, "expires_at_ms": 0}],
                    manifest=None,
                ),
            },
            {
                "case_id": "DF-DEVICE-CONTROL-CONFIGURATION-CHANNEL-WITHOUT-A-BINDING",
                "why": (
                    "A channel entry that carries no binding says a channel exists and "
                    "withholds how to reach it, which is worse than saying there is none."
                ),
                "response": response(
                    lifecycle_state="approved",
                    channels=[{**binding, "opaque_binding": ""}],
                    manifest=None,
                ),
            },
        ],
    }
    save("device-control-configuration-response.json", vector)


if __name__ == "__main__":
    main()
