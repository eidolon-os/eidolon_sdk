"""On-demand preview of the Host's configured synthesis voice, without a session."""
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field
from .coordination import Identifier


class VoicePreviewRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    request_id: Identifier
    regenerate: bool = False


class VoicePreviewStatus(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    key: Annotated[str, Field(pattern=r'^[a-f0-9]{64}$')]
    state: Literal['generating', 'ready', 'failed']
    audio_available: bool
    voice: str
