#!/usr/bin/env python3
"""Regenerate the goldens for the on-screen setup code and the BLE setup transport.

Four documents, one act. A device with a screen draws a setup code per window and
shows it as a QR code (`setup-qr-payload`); the SRP verifier it derives from that
code has to be the one Espressif's clients compute (`setup-code-verifier`); the
Eidolon endpoints have to fit through a BLE characteristic, which they only do in
chunks (`protocomm-endpoint-chunking`); and the BLE transport itself has a shape a
controller can find and trust (`ble-provisioning-transport`).

Vector A of the verifier is not ours: it is the development salt and verifier the
firmware has shipped in Kconfig since Security 2 was introduced, produced by
ESP-IDF's own `srp6a.py`. Reproducing it is what proves the formula here is the
one the device's clients use.
"""

from __future__ import annotations

import hashlib
import json

from _vector_helpers import save

from eidolon_sdk.device_foundation.v1.endpoint_chunking import (
    FRAME_HEADER_BYTES,
    FRAME_MAGIC,
    FRAME_VERSION,
    MAX_CHUNK_BYTES,
    MAX_FRAME_BYTES,
    REQUEST_LIMITS,
    ChunkedEndpoint,
    Frame,
    FrameOp,
    FrameStatus,
)
from eidolon_sdk.device_foundation.v1.setup_code import (
    SETUP_CODE_USERNAME,
    SRP_3072_G,
    SRP_3072_N,
    SetupQrPayload,
    setup_code_verifier,
    setup_qr_payload_canonical_bytes,
)

SCHEMA = "https://contracts.eidolon.live/device-foundation/v1/common/schemas.schema.json#/$defs/SetupQrPayload"

DEV_SALT = "2133af3845196306f61cb3bb2e18862c"
DEV_VERIFIER = (
    "8aada0073ed32e1b00edd09c3c3371c3411ee39456de8243f0b5268751608c6bc01bb301f0f5c5a6d42425a34c79d89d70145252944890ae75c4a744398cd0af8a2a151e9db6b6b6092272520040328371be8b663705c5a71eb586005fb5c88539afc7429ac475682aefd2106736799905ae896faf682ed565cbe3d8785f3271d35ad9230fd2b3536536dc2ba74b68a158a68a6b695a52b4502de2db65be5683bc3d158bb753a63b10ba4ccda5029788e8bd2e525902a2fc92c79e279fb03671c65c326cf884a81ba1f9ac5b1c78ca0354521e2daf34959bd3946cd839898dfb1da1ba78dfe5f57ab921f98fdd9c62c7c90c96db02d164ecd41e3706f306c3e24446fe7f882fc66610a4a119e05e60f0ef3dcfd34938d3870f6d276018b76c272dde8dc747cc912dd3c48807d12964d847656f16da90c9608a4278a96cf4d5f186eed531247e947892ac2e421b3d1d8fbe0684e445c00ecd218fc054c59855a50737b642c803d3f8e7f7a5a48735e9631de2356816cb86b2394ffac752002cf0"
)

SERVICE_UUID = "3a660000-68be-4447-b745-aa003c85e4e4"


def qr_payload() -> dict:
    ble = {
        "ver": "v1", "name": "eidolon-box3-a1b2c3", "username": SETUP_CODE_USERNAME,
        "pop": "40718256", "transport": "ble", "security": 2,
    }
    softap = dict(ble, name="eidolon-m5stack-stackchan-a1b2c3", transport="softap")
    shapes = {}
    for name, value in (("ble", ble), ("softap", softap)):
        canonical = setup_qr_payload_canonical_bytes(SetupQrPayload.model_validate(value))
        shapes[name] = {
            "payload": value,
            "canonical_utf8": canonical.decode(),
            "canonical_sha256": "sha256:" + hashlib.sha256(canonical).hexdigest(),
        }

    def rejected(case: str, **changes: object) -> dict:
        value = dict(ble)
        value.update(changes)
        return {"case": case, "payload": {k: v for k, v in value.items() if v is not None}}

    return {
        "vector_id": "DF-SETUP-QR-PAYLOAD-001",
        "schema": SCHEMA,
        "espressif_keys": ["name", "pop", "security", "transport", "username", "ver"],
        **shapes,
        "rejected": [
            rejected("seven-digit-code", pop="4071825"),
            rejected("non-digit-code", pop="4071825a"),
            rejected("security-1", security=1),
            rejected("other-username", username="wifiprov"),
            rejected("other-transport", transport="usb"),
            rejected("ble-name-over-29-bytes", name="eidolon-m5stack-stackchan-a1b2c3"),
            rejected("unknown-key", password="40718256"),
            rejected("not-an-eidolon-name", name="PROV_a1b2c3"),
        ],
    }


def verifier() -> dict:
    vector_a = bytes.fromhex(DEV_SALT)
    vector_b = bytes(range(1, 17))
    computed_a = setup_code_verifier(SETUP_CODE_USERNAME, "eidolon-dev-setup", vector_a).hex()
    if computed_a != DEV_VERIFIER:
        raise RuntimeError("the SRP formula here does not reproduce the firmware's development verifier")
    return {
        "vector_id": "DF-SETUP-CODE-VERIFIER-001",
        "group": "RFC5054-3072",
        "n_hex": format(SRP_3072_N, "0768x"),
        "g": SRP_3072_G,
        "hash": "SHA-512",
        "x_formula": "SHA-512(salt || SHA-512(username || ':' || password))",
        "verifier_bytes": 384,
        "salt_bytes": 16,
        "salt_first_byte_nonzero": True,
        "code_digits": 8,
        "weak_codes": sorted({str(d) * 8 for d in range(10)} | {"12345678", "87654321"}),
        "vectors": [
            {
                "name": "firmware-development-pair",
                "username": SETUP_CODE_USERNAME,
                "password": "eidolon-dev-setup",
                "salt_hex": DEV_SALT,
                "verifier_hex": DEV_VERIFIER,
            },
            {
                "name": "screen-code",
                "username": SETUP_CODE_USERNAME,
                "password": "40718256",
                "salt_hex": vector_b.hex(),
                "verifier_hex": setup_code_verifier(SETUP_CODE_USERNAME, "40718256", vector_b).hex(),
            },
        ],
        "rejected_salts_hex": ["00" + "11" * 15, "11" * 15, "11" * 17],
    }


def _put(transfer_id: int, request: bytes, offset: int, size: int) -> bytes:
    chunk = request[offset : offset + size]
    return Frame(FrameOp.PUT, transfer_id, len(chunk), len(request), offset, chunk).encode()


def _get(transfer_id: int, offset: int, accept: int = MAX_CHUNK_BYTES) -> bytes:
    return Frame(FrameOp.GET, transfer_id, accept, 0, offset).encode()


def _script(endpoint: str, request: bytes, response: bytes, pending_polls: int,
            frames: list[bytes]) -> dict:
    """Replay frames against the reference endpoint and record what it answers."""

    polls = {"left": pending_polls}

    def handler(whole: bytes | None) -> bytes | None:
        if whole is not None and whole != request:
            raise RuntimeError("the reference endpoint reassembled the wrong request")
        if polls["left"] > 0:
            polls["left"] -= 1
            return None
        return response

    endpoint_state = ChunkedEndpoint(endpoint, handler)
    steps = [{"request_hex": f.hex(), "response_hex": endpoint_state.handle(f).hex()} for f in frames]
    return {
        "endpoint": endpoint,
        "request_utf8": request.decode(),
        "response_utf8": response.decode(),
        "pending_polls": pending_polls,
        "steps": steps,
    }


def _filler(prefix: str, size: int) -> bytes:
    body = json.dumps({"filler": "x" * size})
    text = (prefix + body)[: size - 1] + "}"
    return text.encode()


def chunking() -> dict:
    descriptor_response = _filler('{"descriptor":', 900)
    trust_request = _filler('{"owner_domain_descriptor":', 1000)
    trust_response = b'{"outcome":"staged"}'

    descriptor = _script(
        "eidolon-descriptor", b"{}", descriptor_response, 0,
        [_put(1, b"{}", 0, 2), _get(1, 0), _get(1, 432), _get(1, 864)],
    )
    trust = _script(
        "eidolon-trust", trust_request, trust_response, 2,
        [
            _put(7, trust_request, 0, 432),
            _put(7, trust_request, 432, 432),
            _put(7, trust_request, 864, 432),
            _get(7, 0),
            _get(7, 0),
            _get(7, 0),
        ],
    )
    narrow = _script(
        "eidolon-status", b"{}", b'{"state":"committed"}', 0,
        [_put(3, b"{}", 0, 2), _get(3, 0, 8), _get(3, 8, 8), _get(3, 16, 8)],
    )
    abort = _script(
        "eidolon-trust", b'{"a":1}', b'{"ok":true}', 0,
        [
            _put(9, b'{"a":1,"b":2}', 0, 4),
            Frame(FrameOp.ABORT, 9, 0, 0, 0).encode(),
            _put(10, b'{"a":1}', 0, 7),
            _get(10, 0),
        ],
    )

    def refused(name: str, endpoint: str, frames: list[bytes]) -> dict:
        case = _script(endpoint, b"{}", b"{}", 0, frames)
        case["name"] = name
        return case

    bad_version = bytearray(_put(2, b"{}", 0, 2))
    bad_version[2] = 2
    refused_cases = [
        refused("unsupported-version", "eidolon-status", [bytes(bad_version)]),
        refused("transfer-id-zero", "eidolon-status", [_put(0, b"{}", 0, 2)]),
        refused("length-mismatch", "eidolon-status",
                [Frame(FrameOp.PUT, 2, 3, 2, 0, b"{}").encode()]),
        refused("request-over-limit", "eidolon-status",
                [Frame(FrameOp.PUT, 2, 2, 65, 0, b"{}").encode()]),
        refused("out-of-order-offset", "eidolon-trust",
                [_put(2, b'{"abcdef":1}', 0, 4), _put(2, b'{"abcdef":1}', 8, 4)]),
        refused("get-unknown-transfer", "eidolon-status", [_get(5, 0)]),
        refused("second-transfer-while-busy", "eidolon-trust",
                [_put(2, b'{"abcdef":1}', 0, 4), _put(3, b"{}", 0, 2)]),
        refused("frame-shorter-than-header", "eidolon-status", [FRAME_MAGIC + b"\x01\x01"]),
    ]
    return {
        "vector_id": "DF-PROTOCOMM-ENDPOINT-CHUNKING-001",
        "magic_hex": FRAME_MAGIC.hex(),
        "version": FRAME_VERSION,
        "header_bytes": FRAME_HEADER_BYTES,
        "header_layout": ">2sBBHHII magic,version,op|status,transfer_id,length,total,offset",
        "max_frame_bytes": MAX_FRAME_BYTES,
        "max_chunk_bytes": MAX_CHUNK_BYTES,
        "security2_tag_bytes": 16,
        "request_limits": REQUEST_LIMITS,
        "ops": {op.name: op.value for op in FrameOp},
        "statuses": {status.name: status.value for status in FrameStatus},
        "framed_endpoints": sorted(REQUEST_LIMITS),
        "never_framed_endpoints": ["proto-ver", "prov-config", "prov-ctrl", "prov-scan", "prov-session"],
        "exchanges": {"descriptor": descriptor, "trust": trust, "narrow_reader": narrow, "abort": abort},
        "refused": refused_cases,
    }


def ble_transport() -> dict:
    uuid_bytes = bytes.fromhex(SERVICE_UUID.replace("-", ""))
    return {
        "vector_id": "DF-BLE-PROVISIONING-TRANSPORT-001",
        "service_uuid": SERVICE_UUID,
        "service_uuid_little_endian_hex": uuid_bytes[::-1].hex(),
        "characteristic_uuid_rule": "the service UUID with its second 16-bit group replaced by the endpoint id",
        "endpoint_discovery": "characteristic-user-description-0x2901",
        "endpoint_ids": {
            "prov-ctrl": "ff4f", "prov-scan": "ff50", "prov-session": "ff51", "prov-config": "ff52",
            "proto-ver": "ff53", "eidolon-descriptor": "ff54", "eidolon-trust": "ff55",
            "eidolon-status": "ff56", "eidolon-terminal-ack": "ff57",
        },
        "example_characteristic_uuid": SERVICE_UUID[:4] + "ff51" + SERVICE_UUID[8:],
        "device_name_max_bytes": 29,
        "device_name_pattern": "^eidolon-[a-z0-9]+-[0-9a-f]{6}$",
        "requested_mtu": 517,
        "framing": "required",
        "terminal_delivery": "disconnect-after-accepted-terminal-ack",
        "proto_ver_app_info": {"label": "eidolon", "ver": "1", "cap": ["frame-v1", "setup-code"]},
        "link_encryption": "none-security2-only",
    }


def main() -> None:
    save("setup-qr-payload.json", qr_payload())
    save("setup-code-verifier.json", verifier())
    save("protocomm-endpoint-chunking.json", chunking())
    save("ble-provisioning-transport.json", ble_transport())


if __name__ == "__main__":
    main()
