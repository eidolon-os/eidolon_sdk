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
              "audio_seconds": ..., "pcm_bytes": ...}

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
