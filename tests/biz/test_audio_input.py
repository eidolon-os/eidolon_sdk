"""The audio-input declaration vocabulary is defensive about what it accepts."""

from eidolon_sdk.biz.audio_input import (
    AUDIO_INPUT_STAGE_PROPERTIES,
    normalize_audio_input_processing,
)


def test_each_stage_is_a_dotted_manifest_property():
    assert AUDIO_INPUT_STAGE_PROPERTIES == {
        "aec": "audio.input.aec",
        "agc": "audio.input.agc",
        "ns": "audio.input.ns",
    }


def test_only_known_stages_with_known_values_survive():
    raw = {"aec": "device", "agc": "none", "ns": "loud", "beamforming": "device", "extra": 1}

    assert normalize_audio_input_processing(raw) == {"aec": "device", "agc": "none"}


def test_non_mapping_and_unhashable_values_are_undeclared():
    assert normalize_audio_input_processing(None) == {}
    assert normalize_audio_input_processing("device") == {}
    assert normalize_audio_input_processing({"agc": ["device"]}) == {}
