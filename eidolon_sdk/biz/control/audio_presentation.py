"""Correlated speech presentation over existing LiveKit byte streams.

Only an explicitly armed session may accept the stream. The trusted Channel
prepares playback.present and waits for acceptance before sending bytes. The
receiver validates sender, stream id and chunk sequence. A normal trailer seals
input; completed is emitted only after the same presentation drains its renderer
and hardware output. playback.stop revokes it before flushing queued audio.
"""

from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field
from .coordination import Identifier

AUDIO_PRESENTATION_TOPIC = "eidolon.audio.presentation"
CONTROL_OP_PLAYBACK_PRESENT = "playback.present"
PCM_SAMPLE_RATE = 16000
PCM_CHANNELS = 1
PCM_SAMPLE_BYTES = 2
MAX_PRESENTATION_BYTES = PCM_SAMPLE_RATE * PCM_SAMPLE_BYTES * 120


class AudioPresentation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal[1] = 1
    session_id: Identifier
    turn_id: Identifier
    stream_id: Identifier
    epoch: Annotated[int, Field(strict=True, ge=1)]
    sample_rate: Literal[16000] = PCM_SAMPLE_RATE
    channels: Literal[1] = PCM_CHANNELS
    format: Literal["pcm_s16le"] = "pcm_s16le"


class AudioPresentationResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    session_id: Identifier
    turn_id: Identifier
    stream_id: Identifier
    epoch: Annotated[int, Field(strict=True, ge=1)]
    rendered_bytes: Annotated[int, Field(strict=True, ge=0, le=MAX_PRESENTATION_BYTES)]
    drained: Literal[True]

    def confirms(self, request: AudioPresentation, sent_bytes: int) -> bool:
        return (
            self.session_id == request.session_id
            and self.turn_id == request.turn_id
            and self.stream_id == request.stream_id
            and self.epoch == request.epoch
            and self.rendered_bytes == sent_bytes
            and sent_bytes > 0
        )
