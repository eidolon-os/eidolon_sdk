"""The on-screen setup code and the chunked endpoint frames, at the SDK boundary."""

from __future__ import annotations

import pytest

from eidolon_sdk.device_foundation.v1 import (
    MAX_CHUNK_BYTES,
    ChunkedEndpoint,
    Frame,
    FrameOp,
    FrameStatus,
    SetupQrPayload,
    decode_frame,
    is_acceptable_setup_code,
    is_acceptable_setup_salt,
    setup_code_verifier,
    setup_qr_payload_canonical_bytes,
)

_PAYLOAD = {
    "ver": "v1",
    "name": "eidolon-box3-a1b2c3",
    "username": "eidolon-setup",
    "pop": "40718256",
    "transport": "ble",
    "security": 2,
}


def test_a_code_anybody_would_try_first_is_not_a_code():
    assert is_acceptable_setup_code("40718256")
    for weak in ("00000000", "77777777", "12345678", "87654321"):
        assert not is_acceptable_setup_code(weak)
    for malformed in ("4071825", "407182561", "4071825a", "４０７１８２５６"):
        assert not is_acceptable_setup_code(malformed)


def test_a_salt_that_starts_with_zero_is_not_a_salt():
    assert is_acceptable_setup_salt(bytes(range(1, 17)))
    assert not is_acceptable_setup_salt(b"\x00" + bytes(15))
    assert not is_acceptable_setup_salt(bytes(range(1, 16)))


def test_the_verifier_is_the_one_the_firmware_has_always_shipped():
    verifier = setup_code_verifier(
        "eidolon-setup", "eidolon-dev-setup", bytes.fromhex("2133af3845196306f61cb3bb2e18862c")
    )
    assert len(verifier) == 384
    assert verifier.hex().startswith("8aada0073ed32e1b00edd09c3c3371c3")


def test_the_qr_payload_is_read_as_strictly_as_the_schema():
    payload = SetupQrPayload.model_validate(_PAYLOAD)
    assert setup_qr_payload_canonical_bytes(payload) == (
        b'{"name":"eidolon-box3-a1b2c3","pop":"40718256","security":2,'
        b'"transport":"ble","username":"eidolon-setup","ver":"v1"}'
    )
    with pytest.raises(ValueError):
        SetupQrPayload.model_validate(dict(_PAYLOAD, password="40718256"))
    with pytest.raises(ValueError):
        SetupQrPayload.model_validate(dict(_PAYLOAD, name="eidolon-m5stack-stackchan-a1b2c3"))
    # The same name is fine on SoftAP, where it is an SSID and has 32 bytes.
    SetupQrPayload.model_validate(
        dict(_PAYLOAD, name="eidolon-m5stack-stackchan-a1b2c3", transport="softap")
    )


def test_a_trust_handover_bigger_than_its_limit_is_refused_before_any_of_it_is_kept():
    endpoint = ChunkedEndpoint("eidolon-trust", lambda whole: b"{}")
    oversized = Frame(FrameOp.PUT, 1, 2, 16 * 1024 + 1, 0, b"{}").encode()
    assert decode_frame(endpoint.handle(oversized)).code == FrameStatus.TOO_LARGE


def test_a_response_is_never_handed_out_in_chunks_larger_than_a_frame_allows():
    response = b"x" * 1000
    endpoint = ChunkedEndpoint("eidolon-descriptor", lambda whole: response)
    endpoint.handle(Frame(FrameOp.PUT, 1, 2, 2, 0, b"{}").encode())
    first = decode_frame(endpoint.handle(Frame(FrameOp.GET, 1, 0xFFFF, 0, 0).encode()))
    assert first.code == FrameStatus.DATA
    assert len(first.chunk) == MAX_CHUNK_BYTES
