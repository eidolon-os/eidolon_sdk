"""Microphone processing a device applies before it publishes audio.

Declared in the device manifest as read-only ``const`` properties
(``audio.input.aec`` / ``.agc`` / ``.ns`` = ``"device"`` | ``"none"``), carried
by the Channel Provider into the device's participant metadata under
``AUDIO_INPUT_METADATA_FIELD``, and read once by the Channel agent.

The Host only adds what the device has not done. A second AGC stacked on
device AGC lifted Reachy Mini's own echo and motor residue into the VAD speech
range and paused playback mid-sentence (2026-11-05). An undeclared stage keeps
the Host default, so existing firmware is unaffected.

Only device manifests and the Host use these names; no client mirrors them on
the session wire, which is why they live outside ``biz.contracts``.
"""

from __future__ import annotations

AUDIO_INPUT_AEC_PROPERTY = "audio.input.aec"
AUDIO_INPUT_AGC_PROPERTY = "audio.input.agc"
AUDIO_INPUT_NS_PROPERTY = "audio.input.ns"
AUDIO_INPUT_STAGE_PROPERTIES = {
    "aec": AUDIO_INPUT_AEC_PROPERTY,
    "agc": AUDIO_INPUT_AGC_PROPERTY,
    "ns": AUDIO_INPUT_NS_PROPERTY,
}
AUDIO_INPUT_DEVICE = "device"
AUDIO_INPUT_NONE = "none"
VALID_AUDIO_INPUT_PROCESSING = frozenset({AUDIO_INPUT_DEVICE, AUDIO_INPUT_NONE})
AUDIO_INPUT_METADATA_FIELD = "audio_input"


def normalize_audio_input_processing(raw: object) -> dict[str, str]:
    """Keep only known stages with valid values; anything else stays undeclared."""
    if not isinstance(raw, dict):
        return {}
    processing: dict[str, str] = {}
    for stage in AUDIO_INPUT_STAGE_PROPERTIES:
        value = raw.get(stage)
        if isinstance(value, str) and value in VALID_AUDIO_INPUT_PROCESSING:
            processing[stage] = value
    return processing
