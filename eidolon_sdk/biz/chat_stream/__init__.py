"""Shared constants for the EidolonAgent Chat stream wire contract.

The proto's ``TurnEvent.data`` is an open Struct; these enums pin the
well-known string values both sides exchange so they stop living only in
proto comments. Values are wire-stable: renaming a member must never change
its ``.value``.
"""

from eidolon_sdk.biz.chat_stream.constants import (
    DeltaRole,
    TerminationCause,
    TurnDoneStatus,
)

__all__ = [
    "DeltaRole",
    "TerminationCause",
    "TurnDoneStatus",
]
