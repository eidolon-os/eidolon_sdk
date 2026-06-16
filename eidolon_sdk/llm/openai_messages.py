"""OpenAI-compatible chat message wire helpers.

These helpers encode protocol invariants only. They do not decide which tools
to call or how a turn should progress.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from typing import Any


class OpenAIToolTranscriptError(ValueError):
    """Raised when an OpenAI-compatible tool transcript is structurally invalid."""


def render_openai_tool_calls(tool_calls: Iterable[Any]) -> list[dict[str, Any]]:
    """Render ToolCall-like objects to OpenAI ``assistant.tool_calls`` payloads.

    Each item may be an object with ``id``, ``name`` and ``arguments``
    attributes or a mapping with those keys.
    """

    return [
        {
            "id": _tool_call_value(call, "id"),
            "type": "function",
            "function": {
                "name": _tool_call_value(call, "name"),
                "arguments": json.dumps(
                    _tool_call_value(call, "arguments", default={}),
                    ensure_ascii=False,
                ),
            },
        }
        for call in tool_calls
    ]


def validate_openai_tool_transcript(messages: Sequence[Mapping[str, Any]]) -> None:
    """Validate the OpenAI invariant linking assistant tool calls to tool results."""

    pending: set[str] = set()
    for index, message in enumerate(messages):
        role = message.get("role")
        if role == "assistant":
            for tool_call in message.get("tool_calls") or ():
                call_id = tool_call.get("id") if isinstance(tool_call, Mapping) else None
                if not call_id:
                    raise OpenAIToolTranscriptError(
                        f"assistant tool_call at index {index} is missing id"
                    )
                pending.add(str(call_id))
        elif role == "tool":
            call_id = message.get("tool_call_id")
            if not call_id or str(call_id) not in pending:
                raise OpenAIToolTranscriptError(
                    f"tool message at index {index} has no preceding assistant tool_call"
                )
            pending.remove(str(call_id))
    if pending:
        missing = ", ".join(sorted(pending))
        raise OpenAIToolTranscriptError(f"assistant tool_call has no tool response: {missing}")


def _tool_call_value(call: Any, key: str, *, default: Any = None) -> Any:
    if isinstance(call, Mapping):
        return call.get(key, default)
    return getattr(call, key, default)
