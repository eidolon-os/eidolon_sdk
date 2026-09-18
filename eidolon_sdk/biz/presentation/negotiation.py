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


OUTPUT_CONTRACT = "eidolon.outputs.v1"


def output_policy_required(
    capabilities: OutputSelection,
    *,
    manifest: dict[str, Any] | None = None,
    requirement: bool | None = None,
) -> bool:
    """New declarations opt in explicitly; old face devices remain protected.

    A malformed or unknown marker must not restore legacy speech. The Provider
    validates the exact contract separately before creating a channel.
    ``requirement`` carries the Hub's projection to management clients; None
    denotes an older Hub response that did not contain that projection.
    """
    marked = manifest is not None and any(
        isinstance(prop, dict) and prop.get("name") == "output.contract"
        for prop in manifest.get("properties", ())
    )
    return capabilities.expression or requirement is True or marked


def validate_output_contract(manifest: dict[str, Any]) -> None:
    markers = [
        prop
        for prop in manifest.get("properties", ())
        if isinstance(prop, dict) and prop.get("name") == "output.contract"
    ]
    if not markers:
        return  # Existing devices have no explicit contract marker.
    if len(markers) != 1 or markers[0].get("writable") is not False:
        raise ValueError("INVALID_OUTPUT_CONTRACT")
    schema = markers[0].get("schema")
    if not isinstance(schema, dict) or schema.get("type") != "string":
        raise ValueError("INVALID_OUTPUT_CONTRACT")
    if schema.get("const") != OUTPUT_CONTRACT:
        raise ValueError("UNSUPPORTED_OUTPUT_CONTRACT")


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
