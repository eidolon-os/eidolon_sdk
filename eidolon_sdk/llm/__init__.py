"""Compatibility exports for :mod:`eidolon_sdk.integrations.llm`."""

from eidolon_sdk.integrations.llm import (
    OpenAIToolTranscriptError,
    render_openai_tool_calls,
    validate_openai_tool_transcript,
)

__all__ = [
    "OpenAIToolTranscriptError",
    "render_openai_tool_calls",
    "validate_openai_tool_transcript",
]
