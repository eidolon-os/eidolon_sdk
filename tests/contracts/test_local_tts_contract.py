"""The local TTS wire contract, and the reason it lives in the SDK.

`eidolon_models` serves this protocol and is on a Host only when that Host
declares `local_tts`; `eidolon_channel` speaks it and is on every Host. Neither
may import the other, so each would otherwise hold its own copy of these
strings — the failure the device⇄server contract module beside this one exists
to end.
"""

from __future__ import annotations

import pytest

from eidolon_sdk.biz.contracts import local_asr, local_tts


def test_the_capability_name_is_one_word_shared_with_everything_that_gates_it() -> None:
    """Ops' closed set, the component's `requires_capability`, the manifest
    entry and the Channel provider name are all this string."""

    assert local_tts.LOCAL_TTS_CAPABILITY == "local_tts"


def test_the_client_and_server_vocabularies_do_not_overlap() -> None:
    """A message is one side's to send. Sharing a name between the two
    directions is how a client comes to answer itself."""

    assert not (local_tts.CLIENT_MESSAGE_TYPES & local_tts.SERVER_MESSAGE_TYPES)


def test_every_retryable_code_is_a_code() -> None:
    assert local_tts.RETRYABLE_ERROR_CODES <= local_tts.ERROR_CODES


def test_the_opening_message_states_the_audio_it_is_about_to_send() -> None:
    """A client learns the format on the connection it will use, not from a
    readiness request that could describe a different process."""

    assert local_tts.CONNECTED in local_tts.SERVER_MESSAGE_TYPES
    assert local_tts.AUDIO_SAMPLE_RATE == 24000
    assert local_tts.AUDIO_CHANNELS == 1
    assert local_tts.AUDIO_FORMAT == "pcm_s16le"


def test_the_two_directions_do_not_share_an_audio_rate_by_accident() -> None:
    """Recognition takes 16 kHz and synthesis produces 24 kHz, because the two
    models were trained that way. Asserted so that a later "tidy-up" that made
    them one number has to argue with this instead of resampling silently."""

    assert local_asr.AUDIO_SAMPLE_RATE == 16000
    assert local_tts.AUDIO_SAMPLE_RATE == 24000


def test_a_request_is_addressable_so_a_late_answer_is_not_misread() -> None:
    """Cancellation makes this load-bearing: a `synthesis_finished` can arrive
    for a request the client already gave up on, and without an id it would be
    credited to the request that followed."""

    request = local_tts.synthesize_message("r-1", "你好")
    assert request[local_tts.REQUEST_ID_FIELD] == "r-1"
    assert request["type"] == local_tts.SYNTHESIZE
    assert local_tts.cancel_message("r-1") == {
        "type": local_tts.CANCEL,
        local_tts.REQUEST_ID_FIELD: "r-1",
    }


def test_there_is_a_stated_limit_on_one_request() -> None:
    """The engine holds an utterance in a fixed RKLLM window: past this the
    request does not degrade, it fails — after the NPU was already spent. A
    client that knows the number can split a turn before sending it."""

    assert local_tts.MAX_TEXT_CHARACTERS > 0


def test_the_endpoint_is_composed_rather_than_configured() -> None:
    """Host and port are a Host's facts, not the protocol's."""

    assert local_tts.stream_url("127.0.0.1", 8770) == "ws://127.0.0.1:8770/v1/stream"
    assert local_tts.stream_url("127.0.0.1", 9999, secure=True).startswith("wss://")
    assert local_tts.LOCAL_TTS_STREAM_PATH.startswith("/")


def test_this_module_can_never_introduce_an_import_cycle() -> None:
    """Pure constants, like the contract module beside it: importable by
    anything, importing nothing of its own package."""

    source = (
        pytest.importorskip("pathlib").Path(local_tts.__file__).read_text(encoding="utf-8")
    )
    for line in source.splitlines():
        if line.startswith(("import ", "from ")):
            assert "eidolon_sdk" not in line, line
