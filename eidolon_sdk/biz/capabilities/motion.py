"""Standard motion package. Platform-specific execution lives in device adapters."""

from eidolon_sdk.biz.presentation.capability_rpc import definitions as motion_definitions

from . import CapabilityDefinition


def definitions():
    return [
        CapabilityDefinition(
            name=name,
            llm_name=name.replace(".", "_"),
            description=value["description"]
            + (" For a gesture accompanying speech, set wait_for_completion=false and submit eidolon_respond in the same response when available. Use true when the answer depends on completion. Accepted is pending, never done."
               if name in {"motion.nod", "motion.shake", "motion.look", "motion.play"} else "")
            + " Software completion is not measured physical arrival. Never claim execution without a successful receipt.",
            input_schema=({**value["input_schema"], "properties": {
                **value["input_schema"]["properties"],
                "wait_for_completion": {"type": "boolean", "default": False,
                    "description": "False: return acceptance and let speech continue while the response-owned action runs. True: wait for completion."},
            }} if name in {"motion.nod", "motion.shake", "motion.look", "motion.play"} else value["input_schema"]),
            supports_background=name in {"motion.nod", "motion.shake", "motion.look", "motion.play"},
            supports_response_attachment=name in {"motion.nod", "motion.shake", "motion.look", "motion.play"},
            required_output="motion",
            body_control=True,
            resource_preview_arguments={"summary": True} if name == "motion.catalog" else None,
            reference_result_path=("result", "clips") if name == "motion.catalog" else (),
            execution_location="device",
            side_effect=name != "motion.catalog",
            preempts_active=name == "motion.stop",
            completion_basis="configuration_applied"
            if name in {"motion.catalog", "behavior.speech_motion", "attention.follow"}
            else "software_sequence",
            idempotent=name in {"motion.catalog", "behavior.speech_motion", "attention.follow"},
            timeout_s=45,
        )
        for name, value in motion_definitions().items()
    ]


_PRESENTATIONS = {
    "motion.look": ("转头看", "朝某个方向看过去，或回正。"),
    "motion.nod": ("点头", "在对话里点头。"),
    "motion.shake": ("摇头", "在对话里摇头。"),
    "motion.play": ("做一个动作", "从设备会的动作里挑一个来做。"),
    "motion.stop": ("停下动作", "停止正在做的动作。"),
    "motion.catalog": ("查看会的动作", "查一下这台设备会做哪些动作。"),
    "behavior.speech_motion": ("说话时配合动作", "说话时身体跟着轻轻摆动。"),
    "attention.follow": ("目光跟随", "看着在场的人，听到说话就转过去。"),
}


def presentations():
    """What the Owner reads about each motion tool (labels for the tool catalog)."""

    return {
        name: {"label": label, "summary": summary, "group": "motion"}
        for name, (label, summary) in _PRESENTATIONS.items()
    }
