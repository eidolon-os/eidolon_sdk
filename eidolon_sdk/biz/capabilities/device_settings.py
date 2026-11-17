"""Device settings: values a device keeps that a person or a Companion may change.

A setting is declared twice under related names, because reading it and
changing it are different facts with different owners:

- The value is an observable Manifest property (``audio.volume``). The device is
  its authority and reports it whenever it changes, for any reason: a command,
  its own buttons, a firmware policy. Nothing on the Host stores what the device
  should be set to; it only knows what the device last said it is.
- Changing it is a registered capability (``audio.volume.set``), executed like
  every other device capability and answered with the value the device applied.
  ``*.adjust`` is the relative form, so "a bit louder" needs no prior read.

Only the setter is offered to the Owner's own app (``owner_control``); the
adjust forms exist for conversation. Each is gated on the output it tunes:
volume on speech, brightness on the display that carries expression, so a
Companion an Owner has not given that output cannot turn its knob either.

A device with a speaker confirms a volume change out loud: one short cue at the
new level once the value settles, and only where nothing else carries it (not
at 0, not during a conversation or while something plays, not when the Owner's
output policy allows no audio cue). It is the device presenting its own
setting, so no caller asks for it and the Host sends nothing more; each device
family plays it from its own settings handler (ESP32: ``ShouldConfirmVolume``
in ``device_settings_core.h``).
"""

from __future__ import annotations

from . import CapabilityDefinition

AUDIO_VOLUME = "audio.volume"
DISPLAY_BRIGHTNESS = "display.brightness"

AUDIO_VOLUME_SET = "audio.volume.set"
AUDIO_VOLUME_ADJUST = "audio.volume.adjust"
DISPLAY_BRIGHTNESS_SET = "display.brightness.set"
DISPLAY_BRIGHTNESS_ADJUST = "display.brightness.adjust"

_PERCENT = {"type": "integer", "minimum": 0, "maximum": 100}
_DELTA = {"type": "integer", "minimum": -100, "maximum": 100}


def _object(field: str, schema: dict) -> dict:
    return {
        "type": "object",
        "properties": {field: dict(schema)},
        "required": [field],
        "additionalProperties": False,
    }


def properties() -> dict[str, dict]:
    """The Manifest property each setting is reported as, exactly as declared.

    A device's declaration must equal this to be read, for the reason a
    capability's must equal its registered action: the Host owns the schema it
    checks a reported value against, and a device cannot widen it.
    """

    return {
        name: {"name": name, "schema": dict(_PERCENT), "observable": True, "writable": False}
        for name in (AUDIO_VOLUME, DISPLAY_BRIGHTNESS)
    }


def definitions() -> list[CapabilityDefinition]:
    common = {
        "execution_location": "device",
        "body_control": True,
        "side_effect": True,
        "idempotent": True,
        "completion_basis": "configuration_applied",
        "timeout_s": 5,
    }
    return [
        CapabilityDefinition(
            name=AUDIO_VOLUME_SET,
            llm_name="set_audio_volume",
            description="把这台设备的播放音量设为一个百分比（0–100）。"
            "Set this device's playback volume to a percentage when the person names a level. "
            "The result is the volume the device applied; never claim a change without it.",
            input_schema=_object("volume", _PERCENT),
            result_schema=_object("volume", _PERCENT),
            required_output="speech",
            owner_control=True,
            **common,
        ),
        CapabilityDefinition(
            name=AUDIO_VOLUME_ADJUST,
            llm_name="adjust_audio_volume",
            description="把这台设备的播放音量调高或调低若干个百分点。"
            "Raise (positive) or lower (negative) this device's playback volume by percentage "
            "points when the person asks for louder or quieter without naming a level; about "
            "10 for 'a bit'. The device clamps to 0–100 and the result is the volume it applied.",
            input_schema=_object("change", _DELTA),
            result_schema=_object("volume", _PERCENT),
            required_output="speech",
            **common,
        ),
        CapabilityDefinition(
            name=DISPLAY_BRIGHTNESS_SET,
            llm_name="set_display_brightness",
            description="把这台设备的屏幕亮度设为一个百分比（0–100）。"
            "Set this device's screen brightness to a percentage when the person names a level. "
            "The result is the brightness the device applied; never claim a change without it.",
            input_schema=_object("brightness", _PERCENT),
            result_schema=_object("brightness", _PERCENT),
            required_output="expression",
            owner_control=True,
            **common,
        ),
        CapabilityDefinition(
            name=DISPLAY_BRIGHTNESS_ADJUST,
            llm_name="adjust_display_brightness",
            description="把这台设备的屏幕调亮或调暗若干个百分点。"
            "Raise (positive) or lower (negative) this device's screen brightness by percentage "
            "points when the person asks for brighter or dimmer without naming a level; about "
            "10 for 'a bit'. The device clamps to 0–100 and the result is the brightness it applied.",
            input_schema=_object("change", _DELTA),
            result_schema=_object("brightness", _PERCENT),
            required_output="expression",
            **common,
        ),
    ]
