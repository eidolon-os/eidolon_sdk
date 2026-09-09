"""The wire contract for a Host's own streaming speech synthesis.

Here for the same reason `local_asr` beside it is: two components speak it and
neither may import the other. `eidolon_models` serves it — but only on a Host
that declares the `local_tts` capability, so it is not on every machine — and
`eidolon_channel` is on every machine and must therefore never depend on it
being installed. Both already depend on ``eidolon-sdk``, which the release
carries beside every component, so this is the one place both can read.

Pure constants, validity sets and two builders — no imports from other
``eidolon_sdk`` submodules, so it cannot introduce an import cycle.

Shape of one request, in order:

    server → {"type": "connected", "protocol_version": 1, "voice_id": ...,
              "sample_rate": 24000, "channels": 1, "format": "pcm_s16le"}
    client → {"type": "synthesize", "request_id": ..., "text": ...}
    server → {"type": "synthesis_started", "request_id": ...}
    server → binary WebSocket frames: raw PCM, 24 kHz, mono, signed 16-bit LE
    server → {"type": "synthesis_finished", "request_id": ...,
              "audio_seconds": ..., "pcm_bytes": ...,
              "minimum_buffer_ms": ..., "late_chunks": ..., ...}

The audio is the reverse direction of `local_asr` and the same kind of stream:
it starts arriving before the utterance is finished, because a Host that waited
for the whole sentence would answer a spoken turn about a second late for no
reason. A client plays each frame as it lands.

Requests are answered one at a time on a connection. The Host has one NPU and
one resident engine behind this; two concurrent requests would not be twice as
fast, they would be two utterances that both break up. A client that wants to
queue does so on its own side, where it knows what may be dropped.

Interruption — the reason `cancel` exists — is the case the product cannot do
without: someone talks over the Eidolon and the speech has to stop now. What
cancel guarantees is that no further audio is *delivered* for that request.
It does not guarantee the Host stops computing it: the engine synthesizes an
utterance to completion, so a cancelled request keeps the NPU until it ends
(a few seconds at most). Stated because it is visible — the next request waits
on it — and because a client must not read "cancelled" as "the Host is free".

Reading the finish report
-------------------------

`synthesis_finished` carries the Host's own measurements of how the synthesis
went. They are here because they are the one class of fact a client cannot
observe for itself: whether the Host stayed ahead of playback.

**`minimum_buffer_ms` is the one that says whether anything was audible.** It
is how much unplayed audio was left at the worst moment; below zero means the
listener heard a gap, and at or above zero means they did not, however
uncomfortable the number looks.

**`late_chunks` is not that, and must not be read as that.** It counts chunks
that arrived after their own deadline, measured from the moment the first one
was ready — which assumes playback starts with zero buffer. For a producer
near real time that is almost every chunk by construction, so it tracks the
*length of the audio*, not the listener's experience: 17 seconds of speech
with nothing audible wrong reports about 17 late chunks. It is kept because it
locates *which* chunk was slow, and named for what it counts because the name
it had before — `underruns` — made three separate readers report dropouts that
never happened.

Every field below `pcm_bytes` is optional: the Host omits one it did not
measure, and an older Host omits ones it did not have. So a client must
distinguish absent from zero — `minimum_buffer_ms` missing means "not
reported", which is not the same as "no gap".
"""

from __future__ import annotations

from typing import Any, Final

#: Bump when the shape above changes in a way an older client would mis-read.
#: Served under ``protocol_version`` in the greeting, so a client can refuse a
#: version it does not understand instead of mis-parsing it.
LOCAL_TTS_PROTOCOL_VERSION: Final = 1

#: The capability a Host must declare for this service to exist on it. The same
#: string as `eidolon_ops.capabilities`, the component's `requires_capability`,
#: and the Channel provider name — one word, so "the config asks for local
#: speech" and "this Host can do local speech" compare directly instead of
#: through a table that could disagree.
LOCAL_TTS_CAPABILITY: Final = "local_tts"

#: The port role the component reserves, as named in its `ops/component.toml`.
#: A Host's own registry resolves it to a number; nothing hard-codes one.
LOCAL_TTS_PORT_ROLE: Final = "tts_stream"

#: Where the stream lives, and where readiness is answered. Paths rather than
#: whole URLs: the host and port are a Host's own facts, not the protocol's.
LOCAL_TTS_STREAM_PATH: Final = "/v1/stream"
LOCAL_TTS_READY_PATH: Final = "/readyz"
LOCAL_TTS_INFO_PATH: Final = "/v1/info"

# -- what the client sends ---------------------------------------------------

SYNTHESIZE: Final = "synthesize"
CANCEL: Final = "cancel"
PING: Final = "ping"
CLOSE_STREAM: Final = "close_stream"

CLIENT_MESSAGE_TYPES: Final = frozenset({SYNTHESIZE, CANCEL, PING, CLOSE_STREAM})

# -- what the server sends ---------------------------------------------------

#: Sent unprompted the moment a stream opens, before the client says anything.
#: Carries `protocol_version` and the audio format this Host will send, so a
#: client learns both on the connection it is about to use rather than from a
#: separate readiness request that could describe a different process.
CONNECTED: Final = "connected"

SYNTHESIS_STARTED: Final = "synthesis_started"
SYNTHESIS_FINISHED: Final = "synthesis_finished"
SYNTHESIS_CANCELLED: Final = "synthesis_cancelled"
PONG: Final = "pong"
ERROR: Final = "error"

SERVER_MESSAGE_TYPES: Final = frozenset(
    {
        CONNECTED,
        SYNTHESIS_STARTED,
        SYNTHESIS_FINISHED,
        SYNTHESIS_CANCELLED,
        PONG,
        ERROR,
    }
)

#: The field the greeting states the served version in.
PROTOCOL_VERSION_FIELD: Final = "protocol_version"

#: Which request a message belongs to. Present on every message about one, so
#: a late `synthesis_finished` for a cancelled request is recognisable as such
#: rather than attributed to the request that followed it.
REQUEST_ID_FIELD: Final = "request_id"

# -- what `synthesis_finished` reports --------------------------------------
#
# Named here rather than left as string literals on each side, which is this
# package's whole reason to exist: renaming `underruns` to `late_chunks` in
# the service silently disabled the client's only quality warning, because
# nothing checked that the two ends still agreed on the word.

#: Always present.
PCM_BYTES_FIELD: Final = "pcm_bytes"

#: How long the audio is. Present whenever the Host measured it.
AUDIO_SECONDS_FIELD: Final = "audio_seconds"

#: Unplayed audio left at the worst moment, in milliseconds. Below zero is an
#: audible gap; absent means the Host did not report one, not that there was
#: none. This is the field to judge a synthesis by.
MINIMUM_BUFFER_MS_FIELD: Final = "minimum_buffer_ms"

#: How many chunks arrived after their own deadline. See the module note: this
#: is a locator, not a verdict, and reading it as a dropout count is wrong.
LATE_CHUNKS_FIELD: Final = "late_chunks"

#: Time to the first PCM frame, in milliseconds.
TTFT_MS_FIELD: Final = "ttft_ms"

#: Synthesis time over audio time once the stream is running.
STEADY_RTF_FIELD: Final = "steady_rtf"

#: Time spent preparing the voice profile, in milliseconds.
PROFILE_MS_FIELD: Final = "profile_ms"

# -- the audio the stream carries -------------------------------------------

#: The engine's own rate. Not negotiable here: the HiFT decoder produces this,
#: and resampling belongs to whoever wants a different rate.
AUDIO_SAMPLE_RATE: Final = 24000
AUDIO_CHANNELS: Final = 1
AUDIO_FORMAT: Final = "pcm_s16le"

# -- why a server refused ---------------------------------------------------

#: Retryable: the engine is already saying something, and this Host says one
#: thing at a time.
ERROR_BUSY: Final = "synthesis_in_progress"
#: Not retryable as sent: the text exceeded what this Host will say in one go.
ERROR_TEXT_TOO_LONG: Final = "text_too_long"
#: Not retryable: the client said something this protocol does not contain.
ERROR_BAD_REQUEST: Final = "bad_request"
#: Retryable: synthesis failed on the Host, not in the request.
ERROR_INTERNAL: Final = "internal_error"
#: Retryable: the engine is loading, or died and is being restarted. Distinct
#: from `internal_error` because it says the Host is not ready *yet*, which is
#: worth waiting for rather than falling back on.
ERROR_ENGINE_UNAVAILABLE: Final = "engine_unavailable"

ERROR_CODES: Final = frozenset(
    {
        ERROR_BUSY,
        ERROR_TEXT_TOO_LONG,
        ERROR_BAD_REQUEST,
        ERROR_INTERNAL,
        ERROR_ENGINE_UNAVAILABLE,
    }
)

#: Which refusals are worth sending again. Carried on the wire as `retryable`
#: too, and stated here so a client need not have received one to know.
RETRYABLE_ERROR_CODES: Final = frozenset(
    {ERROR_BUSY, ERROR_INTERNAL, ERROR_ENGINE_UNAVAILABLE}
)

#: What this Host will say in one request. A cap rather than no cap because the
#: engine holds the whole utterance's context in a fixed RKLLM window: text
#: past this point does not degrade, it fails, and it fails after the Host has
#: already spent the NPU on it. Sentence-splitting belongs to the client, which
#: knows where a turn can be broken.
MAX_TEXT_CHARACTERS: Final = 400

#: What this Host will say in one request *without the audio breaking up*.
#:
#: A different question from `MAX_TEXT_CHARACTERS`, and the gap between them is
#: the trap: a request of 200 characters is accepted, answered, and reported as
#: `status=PASS`, and the listener hears a gap in the middle of it. Refusal and
#: audibility are two limits, so they are two constants.
#:
#: Measured on RK3588 by the buffer floor the service reports as
#: `minimum_buffer_ms` — a chunk arriving after its own deadline is harmless
#: while the buffer stays positive, so the floor is the only quantity that says
#: whether anything was heard:
#:
#:     44 chars   9.80 s   +447 ms
#:     60 chars  13.20 s   +504 ms   <- this value, held over 20 rounds
#:     80 chars  16.88 s   +209 ms
#:    126 chars  26.20 s   -246..-372 ms   <- gaps, every run
#:
#: Past an rtf of 1 the deficit accumulates at about 43 ms per second of audio,
#: and 26 seconds is where it consumes the whole buffer. 60 rather than 80
#: because 80 leaves only 209 ms.
#:
#: Stated here rather than only served over `/v1/info` so a client can check it
#: when it is configured instead of after it is running: exceeding this is not
#: an error the service can return — it comes out as audio the user cannot
#: follow. Splitting on sentence boundaries belongs to the client, which knows
#: where a turn can be broken.
#:
#: Raising this requires new measurements of the buffer floor, not an argument.
SAFE_TEXT_CHARACTERS: Final = 60


class LocalTtsProtocolError(ValueError):
    """A message this protocol does not contain."""


def synthesize_message(request_id: str, text: str) -> dict[str, Any]:
    """The client's request, built rather than spelled out per caller."""

    return {"type": SYNTHESIZE, REQUEST_ID_FIELD: request_id, "text": text}


def cancel_message(request_id: str) -> dict[str, Any]:
    """Stop delivering audio for one request. See the module note on what this
    does and does not promise about the Host."""

    return {"type": CANCEL, REQUEST_ID_FIELD: request_id}


def stream_url(host: str, port: int, *, secure: bool = False) -> str:
    """Where to reach the stream on a Host that has one.

    Takes the host and port rather than a URL because neither belongs to the
    protocol: the component reserves a port *role*, a Host's own registry
    resolves it to a number, and the bind is loopback. A client that wrote a
    URL into its configuration would be carrying a fact that can go stale.
    """

    scheme = "wss" if secure else "ws"
    return f"{scheme}://{host}:{port}{LOCAL_TTS_STREAM_PATH}"
