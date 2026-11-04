"""Chunked frames for the Eidolon setup endpoints, above Security 2.

Protocomm carries one request and one response per exchange, and over BLE an
exchange is one characteristic write and one read: at most 512 bytes on NimBLE
and 481 on Bluedroid, of which Security 2 spends 16 on its tag. The Owner trust
handover is several kilobytes and the setup descriptor close to one, so neither
fits. The SoftAP transport never noticed, because HTTP has no such ceiling.

The frames live in the plaintext of each Security 2 message, so every chunk is
still encrypted and authenticated by the session it travels in. A request that
starts with the two-byte magic is a frame; anything else is a whole request as
before, which keeps SoftAP and older controllers working unchanged. A BLE device
refuses unframed requests, because over BLE they cannot be whole.

Header (16 bytes, big-endian), then the chunk:

====== ==== ================================ ==================================
offset size request (controller -> device)   response (device -> controller)
====== ==== ================================ ==================================
0      2    magic E1 D0                      magic E1 D0
2      1    version 01                       version 01
3      1    op: PUT / GET / ABORT            status
4      2    transfer id, never 0             transfer id, echoed
6      2    PUT: chunk length                DATA: chunk length
            GET: largest chunk accepted      PENDING: retry after, ms
8      4    PUT: total request length        READY/DATA: total response length
12     4    PUT: offset of this chunk        CONTINUE: next offset expected
            GET: offset wanted               DATA: offset of this chunk
====== ==== ================================ ==================================

A request is sent as PUTs in order. Every PUT but the last is answered CONTINUE;
the last is answered READY when the response exists, or PENDING when the device
is still working on it. The controller then GETs the response in order until it
has all of it. Any error status ends the transfer, and the controller ends the
visit, exactly as it does for any other failed exchange today. One transfer is
open per endpoint at a time; a controller that gives one up sends ABORT, which is
answered CONTINUE, before it starts another.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from enum import IntEnum
from typing import Callable

FRAME_MAGIC = b"\xe1\xd0"
FRAME_VERSION = 1
FRAME_HEADER_BYTES = 16
# 448 + the 16-byte Security 2 tag = 464, under both BLE ceilings.
MAX_FRAME_BYTES = 448
MAX_CHUNK_BYTES = MAX_FRAME_BYTES - FRAME_HEADER_BYTES

# The largest request each endpoint accepts. The trust handover's ceiling is the
# one the device already enforces on the unframed path; the others are a few
# times what a real request needs.
REQUEST_LIMITS = {
    "eidolon-descriptor": 64,
    "eidolon-status": 64,
    "eidolon-terminal-ack": 1024,
    "eidolon-trust": 16 * 1024,
}

_HEADER = struct.Struct(">2sBBHHII")


class FrameOp(IntEnum):
    PUT = 0x01
    GET = 0x02
    ABORT = 0x03


class FrameStatus(IntEnum):
    CONTINUE = 0x00
    READY = 0x01
    PENDING = 0x02
    DATA = 0x03
    MALFORMED = 0x80
    SEQUENCE = 0x81
    TOO_LARGE = 0x82
    BUSY = 0x83
    UNKNOWN_TRANSFER = 0x84
    UNSUPPORTED_VERSION = 0x85


@dataclass(frozen=True)
class Frame:
    code: int  # FrameOp for a request, FrameStatus for a response
    transfer_id: int
    length: int
    total: int
    offset: int
    chunk: bytes = b""

    def encode(self) -> bytes:
        return _HEADER.pack(
            FRAME_MAGIC, FRAME_VERSION, self.code, self.transfer_id, self.length, self.total, self.offset
        ) + self.chunk


def is_frame(data: bytes) -> bool:
    return data[:2] == FRAME_MAGIC


def decode_frame(data: bytes) -> Frame:
    """Split a frame into its header and chunk; raise ValueError if it is not one."""

    if len(data) < FRAME_HEADER_BYTES or len(data) > MAX_FRAME_BYTES:
        raise ValueError("frame length out of range")
    magic, version, code, transfer_id, length, total, offset = _HEADER.unpack_from(data)
    if magic != FRAME_MAGIC:
        raise ValueError("not a frame")
    if version != FRAME_VERSION:
        raise UnsupportedFrameVersion(version)
    return Frame(code, transfer_id, length, total, offset, bytes(data[FRAME_HEADER_BYTES:]))


class UnsupportedFrameVersion(ValueError):
    pass


def _status(status: FrameStatus, transfer_id: int, length: int = 0, total: int = 0, offset: int = 0,
            chunk: bytes = b"") -> bytes:
    return Frame(status, transfer_id, length, total, offset, chunk).encode()


class ChunkedEndpoint:
    """The device side of one endpoint's chunked transfers, in one session.

    ``handler`` receives the whole request once its last chunk arrives and
    returns the whole response, or ``None`` while the answer is still being
    worked on; it is then called again on each GET until it answers. This is the
    reference the device's C++ core and the controller's codec are tested
    against through the golden vector.
    """

    def __init__(self, endpoint: str, handler: Callable[[bytes | None], bytes | None]) -> None:
        self._limit = REQUEST_LIMITS[endpoint]
        self._handler = handler
        self._reset()

    def _reset(self) -> None:
        self._transfer_id = 0
        self._request = bytearray()
        self._total = 0
        self._response: bytes | None = None
        self._pending = False
        self._delivered = 0

    def _busy(self) -> bool:
        return self._transfer_id != 0

    def handle(self, data: bytes, *, retry_after_ms: int = 250) -> bytes:
        try:
            frame = decode_frame(data)
        except UnsupportedFrameVersion:
            return _status(FrameStatus.UNSUPPORTED_VERSION, 0)
        except ValueError:
            return _status(FrameStatus.MALFORMED, 0)
        if frame.transfer_id == 0:
            return _status(FrameStatus.MALFORMED, 0)
        if frame.code == FrameOp.ABORT:
            if frame.transfer_id != self._transfer_id:
                return _status(FrameStatus.UNKNOWN_TRANSFER, frame.transfer_id)
            self._reset()
            return _status(FrameStatus.CONTINUE, frame.transfer_id)
        if frame.code == FrameOp.PUT:
            return self._put(frame, retry_after_ms)
        if frame.code == FrameOp.GET:
            return self._get(frame, retry_after_ms)
        return _status(FrameStatus.MALFORMED, frame.transfer_id)

    def _put(self, frame: Frame, retry_after_ms: int) -> bytes:
        if frame.length != len(frame.chunk) or frame.length == 0:
            return _status(FrameStatus.MALFORMED, frame.transfer_id)
        if frame.offset == 0:
            if self._busy():
                return _status(FrameStatus.BUSY, frame.transfer_id)
            if frame.total == 0 or frame.total > self._limit:
                return _status(FrameStatus.TOO_LARGE, frame.transfer_id)
            self._transfer_id = frame.transfer_id
            self._total = frame.total
        elif frame.transfer_id != self._transfer_id:
            return _status(FrameStatus.UNKNOWN_TRANSFER, frame.transfer_id)
        if (
            frame.total != self._total
            or frame.offset != len(self._request)
            or self._response is not None
            or self._pending
            or frame.offset + frame.length > self._total
        ):
            self._reset()
            return _status(FrameStatus.SEQUENCE, frame.transfer_id)
        self._request.extend(frame.chunk)
        if len(self._request) < self._total:
            return _status(FrameStatus.CONTINUE, frame.transfer_id, offset=len(self._request))
        self._response = self._handler(bytes(self._request))
        if self._response is None:
            self._pending = True
            return _status(FrameStatus.PENDING, frame.transfer_id, length=retry_after_ms)
        return _status(FrameStatus.READY, frame.transfer_id, total=len(self._response))

    def _get(self, frame: Frame, retry_after_ms: int) -> bytes:
        if frame.transfer_id != self._transfer_id:
            return _status(FrameStatus.UNKNOWN_TRANSFER, frame.transfer_id)
        if frame.chunk or frame.total != 0 or frame.length == 0:
            return _status(FrameStatus.MALFORMED, frame.transfer_id)
        if self._pending:
            self._response = self._handler(None)
            if self._response is None:
                return _status(FrameStatus.PENDING, frame.transfer_id, length=retry_after_ms)
            self._pending = False
        if self._response is None or frame.offset != self._delivered:
            self._reset()
            return _status(FrameStatus.SEQUENCE, frame.transfer_id)
        size = min(frame.length, MAX_CHUNK_BYTES, len(self._response) - self._delivered)
        chunk = self._response[self._delivered : self._delivered + size]
        reply = _status(
            FrameStatus.DATA, frame.transfer_id, length=len(chunk), total=len(self._response),
            offset=self._delivered, chunk=chunk,
        )
        self._delivered += len(chunk)
        if self._delivered == len(self._response):
            self._reset()
        return reply
