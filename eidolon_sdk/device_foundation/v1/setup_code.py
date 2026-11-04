"""The setup code a device shows on its own screen, and the QR code that carries it.

A device used to open its setup session with a passphrase every build shared and
every controller hard-coded. The session underneath it is SRP-6a, a PAKE, but a
PAKE keyed with a published password authenticates nothing: anyone in radio
range could open it. So a device with a screen now draws a fresh eight-digit code
every time it opens a setup window, derives the SRP verifier from that code on
the device, and shows the code — as digits and inside a QR code — on its display.
Reading the screen is the physical-presence proof; the code never leaves the
device any other way.

The QR payload uses Espressif's own keys (``ver``, ``name``, ``username``,
``pop``, ``transport``, ``security``) so vendor tools can read an Eidolon code,
and is read here as strictly as every other Device Foundation document: an
unknown key is refused, not ignored.

The verifier rule is pinned here rather than left to whichever SRP library a
producer has to hand. ESP-IDF's own on-device generator hashes a salt whose
leading zero byte it has dropped while still reporting sixteen bytes, and both
Espressif clients drop that byte too when they turn the salt into a number. A
salt that starts with zero therefore fails roughly one handshake in 256 for
reasons nobody could see from either end, so a salt that starts with zero is not
a salt this contract allows.
"""

from __future__ import annotations

import hashlib
from typing import Any, Literal

import rfc8785
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .lifecycle import WireEnum

SETUP_QR_PAYLOAD_VERSION = "v1"
SETUP_CODE_USERNAME = "eidolon-setup"
SETUP_CODE_DIGITS = 8
SETUP_CODE_SALT_BYTES = 16
SETUP_CODE_VERIFIER_BYTES = 384
# A BLE device name rides in the scan response, which leaves 29 bytes for it.
# A longer name is truncated by the radio stack, and what it drops first is the
# MAC suffix that tells two boards of the same model apart.
SETUP_BLE_NAME_MAX_BYTES = 29

# RFC 5054 Appendix A, 3072-bit group, as ESP-IDF's protocomm Security 2 uses it.
SRP_3072_N = int(
    "ffffffffffffffffc90fdaa22168c234c4c6628b80dc1cd129024e088a67cc74"
    "020bbea63b139b22514a08798e3404ddef9519b3cd3a431b302b0a6df25f1437"
    "4fe1356d6d51c245e485b576625e7ec6f44c42e9a637ed6b0bff5cb6f406b7ed"
    "ee386bfb5a899fa5ae9f24117c4b1fe649286651ece45b3dc2007cb8a163bf05"
    "98da48361c55d39a69163fa8fd24cf5f83655d23dca3ad961c62f356208552bb"
    "9ed529077096966d670c354e4abc9804f1746c08ca18217c32905e462e36ce3b"
    "e39e772c180e86039b2783a2ec07a28fb5c55df06f4c52c9de2bcbf695581718"
    "3995497cea956ae515d2261898fa051015728e5a8aaac42dad33170d04507a33"
    "a85521abdf1cba64ecfb850458dbef0a8aea71575d060c7db3970f85a6e1e4c7"
    "abf5ae8cdb0933d71e8c94e04a25619dcee3d2261ad2ee6bf12ffa06d98a0864"
    "d87602733ec86a64521f2b18177b200cbbe117577a615d6c770988c0bad946e2"
    "08e24fa074e5ab3143db5bfce0fd108e4b82d120a93ad2caffffffffffffffff",
    16,
)
SRP_3072_G = 5

# Codes a person would guess first. Matter refuses the same set for the same
# reason: a random draw that lands on one is still a code anybody would try.
_WEAK_SETUP_CODES = frozenset(
    {str(digit) * SETUP_CODE_DIGITS for digit in range(10)} | {"12345678", "87654321"}
)


class SetupQrTransport(WireEnum):
    """Which radio the device is listening on for this setup window."""

    BLE = "ble"
    SOFTAP = "softap"


class SetupQrPayload(BaseModel):
    """What the QR code on a device's screen says."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    ver: Literal["v1"] = SETUP_QR_PAYLOAD_VERSION
    # The name the device advertises: its BLE device name, or its SoftAP SSID.
    name: str = Field(min_length=9, max_length=32, pattern=r"^eidolon-[a-z0-9][a-z0-9.-]*$")
    username: Literal["eidolon-setup"] = SETUP_CODE_USERNAME
    # Espressif calls the SRP password "pop". It is the eight digits on screen.
    pop: str = Field(pattern=r"^[0-9]{8}$")
    transport: SetupQrTransport
    security: Literal[2] = 2

    @model_validator(mode="after")
    def _ble_name_fits_the_scan_response(self) -> "SetupQrPayload":
        if self.transport is SetupQrTransport.BLE and len(self.name.encode("utf-8")) > SETUP_BLE_NAME_MAX_BYTES:
            raise ValueError("a BLE device name longer than 29 bytes is truncated on air")
        return self


def setup_qr_payload_from_json(value: Any) -> SetupQrPayload:
    """Read a QR payload exactly as strictly as the schema does."""

    return SetupQrPayload.model_validate(value)


def setup_qr_payload_to_json(payload: SetupQrPayload) -> dict[str, Any]:
    return {
        "name": payload.name,
        "pop": payload.pop,
        "security": payload.security,
        "transport": str(payload.transport),
        "username": payload.username,
        "ver": payload.ver,
    }


def setup_qr_payload_canonical_bytes(payload: SetupQrPayload) -> bytes:
    """The exact bytes a device encodes into its QR code."""

    return rfc8785.dumps(setup_qr_payload_to_json(payload))


def is_acceptable_setup_code(code: str) -> bool:
    """Eight digits, and not one of the codes a person would try first."""

    return (
        len(code) == SETUP_CODE_DIGITS
        and code.isascii()
        and code.isdigit()
        and code not in _WEAK_SETUP_CODES
    )


def is_acceptable_setup_salt(salt: bytes) -> bool:
    """Sixteen bytes whose first byte is not zero; see the module docstring."""

    return len(salt) == SETUP_CODE_SALT_BYTES and salt[0] != 0


def setup_code_verifier(username: str, password: str, salt: bytes) -> bytes:
    """The SRP-6a verifier ESP-IDF Security 2 checks a setup session against.

    ``x = SHA-512(salt || SHA-512(username ":" password))`` and ``v = g^x mod N``,
    written as 384 big-endian bytes.
    """

    inner = hashlib.sha512(f"{username}:{password}".encode("utf-8")).digest()
    x = int.from_bytes(hashlib.sha512(salt + inner).digest(), "big")
    return pow(SRP_3072_G, x, SRP_3072_N).to_bytes(SETUP_CODE_VERIFIER_BYTES, "big")
