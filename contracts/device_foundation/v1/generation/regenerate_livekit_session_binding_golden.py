#!/usr/bin/env python3
"""Regenerate the LiveKit session binding golden.

This document is the inside of `ChannelBinding.opaque_binding`. It is opaque to
the Authority, which is right — the Authority relays `binding_format` and the
blob and must not learn what a room is. It is not opaque at all to the pair
that actually uses it: the Channel Provider writes it and every Body parses it,
and until this vector each of them held its own hand-written copy of the shape.
`schema_version: 2` is the record of that having already gone wrong once.
"""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path

import rfc8785

ROOT = Path(__file__).resolve().parents[1]

BINDING_FORMAT = "application/vnd.eidolon.livekit-session+json;v=2"
IDENTITY = "device-instance-591d7c62d0bc738376935f77ff2acd5472bbee64207a765df03af6d6240c07dc"
ROOM_NAME = "eidolon-device-9f1c0a4d2b6e8f3a5c7d1e04"
SERVER_URL = "wss://livekit.owner.test:7880"
TOKEN = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
    ".eyJpc3MiOiJBUElleGFtcGxlIiwic3ViIjoiZGV2aWNlIiwidmlkZW8iOnsicm9vbSI6ImV4YW1wbGUifX0"
    ".Wm9uMV9zaWduYXR1cmVfcGxhY2Vob2xkZXJfZm9yX2Egdmlld2Vy"
)


def binding() -> dict:
    return {
        "schema_version": 2,
        "session": {
            "server_url": SERVER_URL,
            "token": TOKEN,
            "identity": IDENTITY,
            "room_name": ROOM_NAME,
        },
        "audio": {"sample_rate": 16000, "channels": 1},
    }


def main() -> None:
    document = binding()
    canonical = rfc8785.dumps(document)
    # What this vector can and cannot separate, decided here rather than left to
    # whatever the payload happened to be. The standard and URL-safe alphabets
    # differ in two characters, and those two can only appear when a byte at a
    # particular alignment is `?`, `>`, `~` or non-ASCII — none of which occur in
    # a document of ASCII JSON like this one, so for these bytes the alphabets
    # agree and only the padding differs. Padding is the live hazard anyway:
    # every other base64 in this contract (keys, signatures, proofs) is URL-safe
    # and unpadded, so a producer reaching for the house idiom here emits
    # something no Body can decode. The length is therefore held off a multiple
    # of three, which is what makes the padded and unpadded forms differ at all.
    if len(canonical) % 3 == 0:
        raise RuntimeError(
            "the canonical binding is a multiple of three bytes long, so its padded and "
            "unpadded encodings are identical and this vector would separate nothing: "
            "change the token by one character"
        )
    standard = base64.b64encode(canonical).decode("ascii")
    url_safe = base64.urlsafe_b64encode(canonical).rstrip(b"=").decode("ascii")
    vector = {
        "vector_id": "DF-LIVEKIT-SESSION-BINDING-001",
        "description": (
            "The document a Channel Provider seals into `ChannelBinding.opaque_binding`, and "
            "the exact bytes a Body decodes back out of it. The Authority relays it without "
            "reading it; this vector is the agreement between the two ends that do."
        ),
        "no_schema_because": (
            "The canonical schemas are held host- and transport-independent, and "
            "conformance enforces it: `room_name` is a refused key and `livekit` a refused "
            "substring in every *.schema.json and valid example. That rule is right and this "
            "document does not get an exception from it — a Body's addressing must not be "
            "describable in the vocabulary every Body shares. So the agreement between the "
            "Provider and the Body lives here, in a vector, where naming a transport is "
            "exactly what the artifact is for."
        ),
        "binding_format": BINDING_FORMAT,
        "binding": document,
        "canonical_utf8": canonical.decode("utf-8"),
        "canonical_sha256": "sha256:" + hashlib.sha256(canonical).hexdigest(),
        "opaque_binding_encoding": "base64-standard-with-padding",
        "opaque_binding": standard,
        # Named so the mistake has a name, and so a consumer can assert it is
        # not what it produced. A Body decoding the unpadded form fails closed,
        # which is the tolerable half; a Provider emitting it strands every Body.
        "not_the_opaque_binding": {"base64url_no_padding": url_safe},
        # The member set, spelled out so a producer can be held to it rather
        # than to the loose fact that its output "parses". A member added on
        # one side and unknown on the other is how this document reached
        # version 2; a member dropped is a Body that joins nothing.
        "member_paths": [
            "audio.channels",
            "audio.sample_rate",
            "schema_version",
            "session.identity",
            "session.room_name",
            "session.server_url",
            "session.token",
        ],
        "must_refuse": [
            {
                "case_id": "DF-LIVEKIT-SESSION-BINDING-SCHEMA-VERSION-3",
                "why": (
                    "A version this vocabulary does not define. Reading it as if it were 2 is "
                    "how a field that moved becomes a Body holding a room it cannot use."
                ),
                "binding": {**document, "schema_version": 3},
            },
            {
                "case_id": "DF-LIVEKIT-SESSION-BINDING-NO-TOKEN",
                "why": "A room nobody may enter is not a channel, and an empty token is not one.",
                "binding": {**document, "session": {**document["session"], "token": ""}},
            },
            {
                "case_id": "DF-LIVEKIT-SESSION-BINDING-SAMPLE-RATE-OUT-OF-RANGE",
                "why": (
                    "Outside the range a Body in this system opens a capture at. A rate "
                    "accepted and then not honoured is silence with nothing reporting it."
                ),
                "binding": {**document, "audio": {"sample_rate": 96000, "channels": 1}},
            },
            {
                "case_id": "DF-LIVEKIT-SESSION-BINDING-THREE-CHANNELS",
                "why": "Mono or stereo. There is no third thing a Body knows how to play.",
                "binding": {**document, "audio": {"sample_rate": 16000, "channels": 3}},
            },
        ],
    }
    path = ROOT / "golden" / "livekit-session-binding.json"
    path.write_text(json.dumps(vector, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote golden/{path.name}")


if __name__ == "__main__":
    main()
