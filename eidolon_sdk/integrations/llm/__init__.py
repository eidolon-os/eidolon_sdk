"""LLM provider wire-format contracts shared by Eidolon projects."""

from .openai_messages import (
    OpenAIToolTranscriptError,
    render_openai_tool_calls,
    validate_openai_tool_transcript,
)

__all__ = [
    "OpenAIToolTranscriptError",
    "render_openai_tool_calls",
    "validate_openai_tool_transcript",
]
