"""Transport-neutral selection from immutable capabilities and trusted policy."""

from typing import Any
from . import FACE_PROFILE, OutputSelection, DeviceOutputPolicy


def declared_constant(manifest: dict[str, Any], name: str) -> Any:
    for prop in manifest.get("properties", ()):
        if isinstance(prop, dict) and prop.get("name") == name and prop.get("writable") is False:
            schema = prop.get("schema")
            if isinstance(schema, dict):
                return schema.get("const")
    return None


def manifest_outputs(manifest: dict[str, Any]) -> OutputSelection:
    speech = any(
        isinstance(media, dict)
        and media.get("kind") == "audio"
        and media.get("direction") in {"subscribe", "bidirectional"}
        for media in manifest.get("media", ())
    )
    return OutputSelection(
        speech=speech,
        dialogue_text=declared_constant(manifest, "output.dialogue_text") is True,
        expression=declared_constant(manifest, "expression.profile") == FACE_PROFILE,
        audio_cue=declared_constant(manifest, "output.audio_cue") is True,
        motion=declared_constant(manifest, "output.motion") is True,
    )


def select_outputs(
    *,
    capabilities: OutputSelection,
    policy: DeviceOutputPolicy,
    requested: OutputSelection,
    ceiling: OutputSelection,
    require_response: bool = True,
) -> OutputSelection:
    selected = capabilities.restrict(policy.allowed).restrict(requested).restrict(ceiling)
    if require_response and not selected.can_respond:
        raise ValueError("NO_RESPONSE_OUTPUT")
    return selected
