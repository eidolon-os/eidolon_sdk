"""The wire contract for a Host's own streaming speech recognition.

Defined here for the reason the rest of this package exists: two components
speak it and neither may import the other. `eidolon_models` serves it — but
only on a Host that declares the `local_asr` capability, so it is not on every
machine — and `eidolon_channel` is on every machine and must therefore never
depend on it being installed. Both already depend on ``eidolon-sdk``, which the
release carries beside every component, so this is the one place both can read.

The alternative was each side holding its own copy of these strings, which is
exactly the failure the device⇄server contract module beside this one was
written to end: a single typo degrades silently, in a direction nothing checks.

Pure constants, validity sets and one parser for the client's side of the
handshake — no imports from other ``eidolon_sdk`` submodules, so it cannot
introduce an import cycle.

Shape of one utterance, in order:

    client → {"type": "start_utterance", "stream_id": ..., "utterance_id": ...}
    server → {"type": "utterance_started", ...}
    client → binary WebSocket frames: raw PCM, 16 kHz, mono, signed 16-bit LE
    server → {"type": "transcript", "is_final": false, "text": ...}   (repeats)
    client → {"type": "end_utterance"}
    server → {"type": "transcript", "is_final": true, "text": ...}

The two-pass shape is the point and is why a local Host can do something a
provider cannot: the interim answers come from a streaming model as the words
arrive, and the final one is re-decoded by an offline model and punctuated. A
client renders the interims and replaces them with the final.
"""

from __future__ import annotations

from typing import Any, Final

#: Bump when the shape below changes in a way an older client would mis-read.
#: Served under ``protocol_version`` on the readiness document, so a client can
#: refuse a version it does not understand instead of mis-parsing it.
LOCAL_ASR_PROTOCOL_VERSION: Final = 1

#: The capability a Host must declare for this service to exist on it. The same
#: string as `eidolon_ops.capabilities`, the component's `requires_capability`,
#: and the Channel provider name — one word, so "the config asks for local
#: speech" and "this Host can do local speech" compare directly instead of
#: through a table that could disagree.
LOCAL_ASR_CAPABILITY: Final = "local_asr"

#: The port role the component reserves, as named in its `ops/component.toml`.
#: A Host's own registry resolves it to a number; nothing hard-codes one.
LOCAL_ASR_PORT_ROLE: Final = "asr_stream"

#: Where the stream lives, and where readiness is answered. Paths rather than
#: whole URLs: the host and port are a Host's own facts, not the protocol's.
LOCAL_ASR_STREAM_PATH: Final = "/v1/stream"
LOCAL_ASR_READY_PATH: Final = "/readyz"
LOCAL_ASR_INFO_PATH: Final = "/v1/info"

# -- what the client sends ---------------------------------------------------

START_UTTERANCE: Final = "start_utterance"
END_UTTERANCE: Final = "end_utterance"
PING: Final = "ping"
CLOSE_STREAM: Final = "close_stream"

#: Accepted alongside `start_utterance` by servers that predate the longer
#: name. New clients send the long one; the short one is not removed here
#: because a server may still be asked to read it.
START_UTTERANCE_LEGACY: Final = "start"

CLIENT_MESSAGE_TYPES: Final = frozenset(
    {START_UTTERANCE, START_UTTERANCE_LEGACY, END_UTTERANCE, PING, CLOSE_STREAM}
)

# -- what the server sends ---------------------------------------------------

UTTERANCE_STARTED: Final = "utterance_started"
TRANSCRIPT: Final = "transcript"
PONG: Final = "pong"
ERROR: Final = "error"

SERVER_MESSAGE_TYPES: Final = frozenset({UTTERANCE_STARTED, TRANSCRIPT, PONG, ERROR})

#: Distinguishes an answer that may still change from the one that will not.
IS_FINAL_FIELD: Final = "is_final"

# -- the audio the stream carries -------------------------------------------

AUDIO_SAMPLE_RATE: Final = 16000
AUDIO_CHANNELS: Final = 1
AUDIO_FORMAT: Final = "pcm_s16le"

# -- why a server refused ---------------------------------------------------

#: Retryable: the Host is busy, and the same request later may be served.
ERROR_CAPACITY: Final = "connection_capacity_exceeded"
#: Not retryable as sent: the utterance exceeded what this Host will hold.
ERROR_UTTERANCE_TOO_LONG: Final = "utterance_too_long"
#: Not retryable: the client said something this protocol does not contain.
ERROR_BAD_REQUEST: Final = "bad_request"
#: Retryable: recognition failed on the Host, not in the request.
ERROR_INTERNAL: Final = "internal_error"

ERROR_CODES: Final = frozenset(
    {ERROR_CAPACITY, ERROR_UTTERANCE_TOO_LONG, ERROR_BAD_REQUEST, ERROR_INTERNAL}
)

#: Which refusals are worth sending again. Carried on the wire as `retryable`
#: too, and stated here so a client need not have received one to know.
RETRYABLE_ERROR_CODES: Final = frozenset({ERROR_CAPACITY, ERROR_INTERNAL})


class LocalAsrProtocolError(ValueError):
    """A message this protocol does not contain."""


def start_message(stream_id: str, utterance_id: str) -> dict[str, Any]:
    """The client's opening message, built rather than spelled out per caller."""

    return {
        "type": START_UTTERANCE,
        "stream_id": stream_id,
        "utterance_id": utterance_id,
        "sample_rate": AUDIO_SAMPLE_RATE,
        "channels": AUDIO_CHANNELS,
        "format": AUDIO_FORMAT,
    }


def stream_url(host: str, port: int, *, secure: bool = False) -> str:
    """Where to reach the stream on a Host that has one.

    Takes the host and port rather than a URL because neither belongs to the
    protocol: the component reserves a port *role*, a Host's own registry
    resolves it to a number, and the bind is loopback. A client that wrote a
    URL into its configuration would be carrying a fact that can go stale.
    """

    scheme = "wss" if secure else "ws"
    return f"{scheme}://{host}:{port}{LOCAL_ASR_STREAM_PATH}"
