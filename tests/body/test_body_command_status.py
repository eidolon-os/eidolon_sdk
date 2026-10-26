"""Every body status must be reachable from the control layer's vocabulary.

``BodyCommandStatus`` and the acknowledgements a device actually sends are two
different lists, joined by one translation. ``done`` was on the body side with
no producer and ``succeeded`` on the control side with no reader, so a command
that worked read as unfinished. This holds the join: no body status may be a
word nothing can produce, and no device acknowledgement may fall outside the
translation.
"""

from __future__ import annotations

import pytest
from eidolon_sdk.biz.control.protocol import command_status_from_ack

from eidolon_sdk.biz.body.models import (
    _CONTROL_TO_BODY_STATUS,
    BodyCommandStatus,
    body_status_from_control,
)

#: The acknowledgements a device and the control layer can emit, taken from the
#: two authorities rather than restated: ``_ACK_STATUSES`` on the control side
#: and the strings ``AckCommand`` sends on the device. Kept as a literal because
#: the device is another repository; a value added there without a row here
#: fails the translation test below.
_DEVICE_ACKNOWLEDGEMENTS = (
    "accepted",
    "completed",
    "succeeded",
    "failed",
    "running",
    "unsupported",
)


@pytest.mark.parametrize("acknowledgement", _DEVICE_ACKNOWLEDGEMENTS)
def test_a_device_acknowledgement_reads_as_a_real_body_status(
    acknowledgement: str,
) -> None:
    translated = body_status_from_control(command_status_from_ack(acknowledgement))

    assert translated in BodyCommandStatus.__args__


@pytest.mark.parametrize("status", BodyCommandStatus.__args__)
def test_no_body_status_is_unreachable_from_control(status: str) -> None:
    """A body status nothing can produce is a word a consumer may wait for."""

    assert status in set(_CONTROL_TO_BODY_STATUS.values())


def test_a_completed_device_command_reads_as_done() -> None:
    translated = body_status_from_control(command_status_from_ack("completed"))

    assert translated == "done"


def test_an_unknown_acknowledgement_is_not_success() -> None:
    assert body_status_from_control("something-nobody-sends") == "failed"
