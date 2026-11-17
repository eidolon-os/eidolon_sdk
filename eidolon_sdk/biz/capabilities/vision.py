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
            # What the tool does, when to use it, what the result means and what it
            # never allows. Not how to word the answer: the model reads this on every
            # turn the tool is offered and repeats any wording it is given (four
            # identical "you are X" answers in a row, 2026-11-14).
            description="Look through the device camera and check who is in view against the "
            "people whose faces the Owner enrolled. Use it when the user asks whether you "
            "know or recognize them, who they are, or who is here. It only knows enrolled "
            "people; everyone else is unknown. The person speaking is named only by "
            "address_as, present only when a name may be used for them; without it, who is "
            "speaking is not known, whatever names appear elsewhere in the result. summary "
            "states the outcome in words. Knowing who someone is never makes it right to "
            "share anyone's private information.",
            input_schema={"type": "object", "additionalProperties": False, "properties": {}},
            result_schema={
                "type": "object",
                "additionalProperties": False,
                "required": ["faces", "enrolled", "visible", "voice", "agreement", "summary"],
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
                    # The outcome in words: facts and what not to do, never how to
                    # phrase the reply.
                    "summary": {"type": "string", "maxLength": 512},
                },
            },
            required_input="camera",
            execution_location="channel",
            side_effect=False,
            idempotent=False,
            timeout_s=12,
        )
    ]


def presentations():
    """What the Owner reads about each vision tool (labels for the tool catalog)."""

    return {
        VISION_WHO: {
            "label": "认出画面里的人",
            "summary": "用摄像头看看是谁，只认得你登记过脸的人。",
            "group": "vision",
            "host_feature": "face_recognition",
        },
    }
