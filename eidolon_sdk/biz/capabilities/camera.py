"""Camera contracts: one still on request. Taking the frame lives in device adapters.

The image never travels in the capability result. The device sends it to the
session peer as one byte stream on ``FRAME_TOPIC`` before it reports completion,
and the result carries only what the receiver needs to match and check it.
"""

from eidolon_sdk.biz.presentation import CAMERA_CAPTURE

from . import CapabilityDefinition

FRAME_TOPIC = "eidolon.camera.frame.v1"
FRAME_MEDIA_TYPE = "image/jpeg"
MAX_FRAME_BYTES = 512 * 1024
# Byte-stream attributes, all strings: the execution the frame answers and the
# session binding the device took it under.
ATTRIBUTE_EXECUTION = "execution_id"
ATTRIBUTE_SESSION = "session_id"
ATTRIBUTE_POLICY_REVISION = "policy_revision"
ATTRIBUTE_SHA256 = "sha256"

ERRORS = ("camera_disabled", "camera_unavailable", "no_frame", "transfer_failed")


def definitions():
    return [
        CapabilityDefinition(
            name=CAMERA_CAPTURE,
            llm_name="camera_capture",
            description="Take one still from the device camera and send it to the Host. "
            "Used by the Agent to answer a question about what is in front of the device; "
            "never offered to the model directly.",
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "purpose": {"type": "string", "enum": ["look"], "default": "look"},
                    "max_edge": {"type": "integer", "minimum": 256, "maximum": 1280, "default": 768},
                    "quality": {"type": "integer", "minimum": 50, "maximum": 95, "default": 80},
                },
            },
            result_schema={
                "type": "object",
                "properties": {
                    "media_type": {"type": "string"},
                    "width": {"type": "integer"},
                    "height": {"type": "integer"},
                    "bytes": {"type": "integer"},
                    "sha256": {"type": "string"},
                    "captured_at_ms": {"type": "integer"},
                    # read: the moment the frame was read, the closest a device
                    # without sensor timestamps can state. capture: sensor time.
                    "timestamp_kind": {"type": "string", "enum": ["read", "capture"]},
                    "roll_deg": {"type": "number"},
                },
            },
            required_input="camera",
            model_tool=False,
            execution_location="device",
            side_effect=False,
            idempotent=False,
            timeout_s=10,
        )
    ]
