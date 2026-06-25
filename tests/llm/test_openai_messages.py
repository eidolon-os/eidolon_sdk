from __future__ import annotations

from dataclasses import dataclass

import pytest

from eidolon_sdk.integrations.llm import (
    OpenAIToolTranscriptError,
    render_openai_tool_calls,
    validate_openai_tool_transcript,
)


@dataclass(frozen=True)
class _ToolCall:
    id: str
    name: str
    arguments: dict


def test_render_openai_tool_calls_accepts_objects() -> None:
    out = render_openai_tool_calls(
        [_ToolCall(id="call-1", name="get_time", arguments={"timezone": "Asia/Shanghai"})]
    )

    assert out == [
        {
            "id": "call-1",
            "type": "function",
            "function": {
                "name": "get_time",
                "arguments": '{"timezone": "Asia/Shanghai"}',
            },
        }
    ]


def test_validate_openai_tool_transcript_accepts_paired_messages() -> None:
    validate_openai_tool_transcript(
        [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"id": "call-1", "type": "function"}],
            },
            {"role": "tool", "tool_call_id": "call-1", "content": "{}"},
        ]
    )


def test_validate_openai_tool_transcript_rejects_orphan_tool_message() -> None:
    with pytest.raises(OpenAIToolTranscriptError, match="no preceding assistant"):
        validate_openai_tool_transcript(
            [{"role": "tool", "tool_call_id": "call-1", "content": "{}"}]
        )


def test_validate_openai_tool_transcript_rejects_missing_tool_response() -> None:
    with pytest.raises(OpenAIToolTranscriptError, match="no tool response"):
        validate_openai_tool_transcript(
            [
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [{"id": "call-1", "type": "function"}],
                }
            ]
        )
