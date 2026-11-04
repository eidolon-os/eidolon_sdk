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
            if name in {"motion.catalog", "behavior.speech_motion"}
            else "software_sequence",
            idempotent=name in {"motion.catalog", "behavior.speech_motion"},
            timeout_s=45,
        )
        for name, value in motion_definitions().items()
    ]
