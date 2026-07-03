"""Well-known TurnEvent.data string values (see eidolon.proto comments)."""

from __future__ import annotations

from enum import Enum


class DeltaRole(str, Enum):
    """DELTA.data.role — how the renderer should treat a text delta."""

    # Spoken answer content (the default when role is absent on the wire).
    ANSWER = "answer"
    # Status line announcing a tool call; routed to UI, never spoken.
    TOOL_PREAMBLE = "tool_preamble"
    # Delayed spoken wait hint while a slow tool / slow path runs.
    SLOW_TOOL_HINT = "slow_tool_hint"


class TurnDoneStatus(str, Enum):
    """DONE.data.status — how the turn ended."""

    OK = "ok"
    CANCELLED = "cancelled"
    ERRORED = "errored"
    HANDED_OFF = "handed_off"


class TerminationCause(str, Enum):
    """DONE.data.termination_cause — WHY the turn ended.

    ``USER_STOP`` means the brain classified the utterance itself as a stop
    command and never invoked the LLM; upstream should circuit-break TTS and
    rendering for the turn. ``CLIENT_CANCEL`` acknowledges a CancelTurn
    frame; ``RPC_CANCEL`` means the transport went away mid-turn.
    """

    NORMAL = "normal"
    USER_STOP = "user_stop"
    CLIENT_CANCEL = "client_cancel"
    RPC_CANCEL = "rpc_cancel"
    GUARDRAIL = "guardrail"
    ERROR = "error"
