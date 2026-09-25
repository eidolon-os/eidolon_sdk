"""Generate shared-invitation and rejection vectors with the production SDK."""
from pathlib import Path
import json
from eidolon_sdk.biz.control.shared_session import SharedSessionInvitation
from eidolon_sdk.biz.contracts import (
    CHANNEL_PROVIDER_IDENTITY_PREFIX, SESSION_REJECTED_TYPE,
    SESSION_REJECTION_CONFLICT, WIRE_SCHEMA_VERSION,
)

HERE = Path(__file__).resolve().parent
FOUNDATION = HERE.parents[1] / "device_foundation/v1/golden"


def vectors():
    binding = json.loads((FOUNDATION / "livekit-session-binding.json").read_text())
    ref = json.loads((FOUNDATION / "device-control-configuration-response.json").read_text())["device_ref"]
    invite = SharedSessionInvitation.model_validate_json(json.dumps({
        "session_id": "visit-golden", "device_ref": ref, "deadline_ms": 1700000020000,
        "channel": {"channel_id": "temporary-golden", "purpose": "shared-session",
            "kinds": ["audio", "reliable-data"], "binding_format": binding["binding_format"],
            "issued_at_ms": 1700000000000, "expires_at_ms": 1700000120000,
            "opaque_binding": binding["opaque_binding"]},
    }))
    return {
        "shared-session-invite.json": invite.command(command_id="invite-golden"),
        "session-rejected.json": {
            "provider_identity": CHANNEL_PROVIDER_IDENTITY_PREFIX + "same-room",
            "room": "same-room",
            "payload": {"schema_v": WIRE_SCHEMA_VERSION, "type": SESSION_REJECTED_TYPE,
                "conversation_id": "conversation-1", "reason": SESSION_REJECTION_CONFLICT},
        },
    }


if __name__ == "__main__":
    for name, vector in vectors().items():
        (HERE / "golden" / name).write_text(json.dumps(vector, ensure_ascii=False, indent=2) + "\n")
