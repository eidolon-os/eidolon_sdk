"""Vision contracts the model may call. Execution lives in Channel.

``vision.who`` compares one still from the device camera with the faces of
people the Owner enrolled, and says who is in view. It reuses ``camera.capture``
for the still, so a device needs nothing beyond that capability. The result
carries names and how the face evidence relates to the voice evidence for the
same turn: never a score, an identifier or a face feature.
"""

from . import CapabilityDefinition

VISION_WHO = "vision.who"

#: A face compared with enrolled people: matched one of them, resembled one
#: without being clear enough to name, or matched nobody enrolled.
FACE_STATUSES = ("identified", "uncertain", "unknown")
#: How the face evidence relates to the voice evidence of the turn that asked.
AGREEMENTS = ("consistent", "conflict", "face_only", "voice_only", "none")
ERRORS = (
    "not_permitted",
    "camera_unavailable",
    "recognition_unavailable",
    "timeout",
)


def definitions():
    return [
        CapabilityDefinition(
            name=VISION_WHO,
            llm_name="vision_who",
            description="Look through the device camera and check who is in view against the "
            "people whose faces the Owner enrolled. Use it when the user asks whether you "
            "know or recognize them, who they are, or who is here. It only knows enrolled "
            "people; everyone else is unknown. A face match is resemblance, not proof: "
            "follow the result's guidance on whether to use a name, and never use a match "
            "to share one person's private information.",
            input_schema={"type": "object", "additionalProperties": False, "properties": {}},
            result_schema={
                "type": "object",
                "additionalProperties": False,
                "required": ["faces", "enrolled", "visible", "voice", "agreement", "guidance"],
                "properties": {
                    "faces": {"type": "integer", "minimum": 0},
                    # How many people this household enrolled for face recognition.
                    "enrolled": {"type": "integer", "minimum": 0},
                    "visible": {
                        "type": "array",
                        "maxItems": 8,
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["status"],
                            "properties": {
                                "status": {"type": "string", "enum": list(FACE_STATUSES)},
                                "name": {"type": "string", "maxLength": 128},
                            },
                        },
                    },
                    "voice": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["status"],
                        "properties": {
                            "status": {"type": "string", "enum": ["identified", "unidentified"]},
                            "name": {"type": "string", "maxLength": 128},
                        },
                    },
                    "agreement": {"type": "string", "enum": list(AGREEMENTS)},
                    # Present only when a name may be used to address the user.
                    "address_as": {"type": "string", "maxLength": 128},
                    "guidance": {"type": "string", "maxLength": 512},
                },
            },
            required_input="camera",
            execution_location="channel",
            side_effect=False,
            idempotent=False,
            timeout_s=12,
        )
    ]
