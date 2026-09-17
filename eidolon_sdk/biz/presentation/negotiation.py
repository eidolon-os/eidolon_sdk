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


def output_policy_required(capabilities: OutputSelection) -> bool:
    """Whether this device cannot be served until its Owner has decided.

    A device that can show this product's face is one whose speech has to be a
    grant rather than a leftover default, so an absent policy is a question and
    not an answer, and nothing may negotiate on its behalf. Devices that predate
    the vocabulary keep running on the legacy outputs instead — which is why
    this is one predicate and not a rule each consumer states for itself: the
    Provider refuses by it, and a management surface says "not decided yet" by
    it, and they cannot come to mean different things.
    """

    return capabilities.expression


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
