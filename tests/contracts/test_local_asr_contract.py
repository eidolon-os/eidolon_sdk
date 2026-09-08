"""The local ASR wire contract, and the reason it lives in the SDK.

`eidolon_models` serves this protocol and is on a Host only when that Host
declares `local_asr`; `eidolon_channel` speaks it and is on every Host. Neither
may import the other, so each would otherwise hold its own copy of these
strings — the failure the device⇄server contract module beside this one exists
to end.
"""

from __future__ import annotations

import pytest

from eidolon_sdk.biz.contracts import local_asr


def test_the_capability_name_is_one_word_shared_with_everything_that_gates_it() -> None:
    """Ops' closed set, the component's `requires_capability`, the manifest
    entry and the Channel provider name are all this string.

    One word rather than a mapping table: "the config asks for local speech"
    and "this Host can do local speech" then compare directly, and a table that
    disagreed with itself is not expressible.
    """

    assert local_asr.LOCAL_ASR_CAPABILITY == "local_asr"


def test_the_client_and_server_vocabularies_do_not_overlap() -> None:
    """A message is one side's to send. Sharing a name between the two
    directions is how a client comes to answer itself."""

    assert not (local_asr.CLIENT_MESSAGE_TYPES & local_asr.SERVER_MESSAGE_TYPES)


def test_every_retryable_code_is_a_code() -> None:
    assert local_asr.RETRYABLE_ERROR_CODES < local_asr.ERROR_CODES


def test_the_opening_message_states_the_audio_it_is_about_to_send() -> None:
    """The server accepts one audio shape and says so; the client declares it
    rather than letting a mismatch surface as bad recognition."""

    message = local_asr.start_message("stream-1", "utterance-1")

    assert message["type"] == local_asr.START_UTTERANCE
    assert message["sample_rate"] == local_asr.AUDIO_SAMPLE_RATE == 16000
    assert message["channels"] == local_asr.AUDIO_CHANNELS == 1
    assert message["format"] == local_asr.AUDIO_FORMAT == "pcm_s16le"
    assert message["stream_id"] == "stream-1"
    assert message["utterance_id"] == "utterance-1"


def test_the_endpoint_is_composed_rather_than_configured() -> None:
    """Host and port are a Host's facts, not the protocol's. A client that wrote
    a URL into its configuration would carry a value that can go stale — which
    is the defect this repository spent a day removing elsewhere."""

    assert local_asr.stream_url("127.0.0.1", 8768) == "ws://127.0.0.1:8768/v1/stream"
    assert local_asr.stream_url("127.0.0.1", 9999, secure=True).startswith("wss://")
    assert local_asr.LOCAL_ASR_STREAM_PATH.startswith("/")


def test_this_module_can_never_introduce_an_import_cycle() -> None:
    """Pure constants, like the contract module beside it: importable by
    anything, importing nothing of its own package."""

    source = (
        pytest.importorskip("pathlib").Path(local_asr.__file__).read_text(encoding="utf-8")
    )
    for line in source.splitlines():
        if line.startswith(("import ", "from ")):
            assert "eidolon_sdk" not in line, line
