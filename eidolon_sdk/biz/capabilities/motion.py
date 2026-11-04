"""Standard motion package. Platform-specific execution lives in device adapters."""

from eidolon_sdk.biz.presentation.capability_rpc import definitions as motion_definitions

from . import CapabilityDefinition


def definitions():
    return [
        CapabilityDefinition(
            name=name,
            llm_name=name.replace(".", "_"),
            description=value["description"]
            + " Wait for the receipt. Software completion is not measured physical arrival. Never claim execution without a successful receipt.",
            input_schema=value["input_schema"],
            required_output="motion",
            body_control=True,
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
