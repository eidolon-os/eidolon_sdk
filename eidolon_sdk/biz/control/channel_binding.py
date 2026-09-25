"""Provider-owned opaque Channel binding; shared by configuration and invitations."""

from pydantic import BaseModel, ConfigDict, Field


class ChannelBinding(BaseModel):
    """Provider-owned opaque binding exposed by Device Control configuration."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    channel_id: str = Field(min_length=1, max_length=128)
    purpose: str = Field(min_length=1, max_length=64)
    kinds: tuple[str, ...] = Field(min_length=1, max_length=8)
    binding_format: str = Field(min_length=1, max_length=128)
    issued_at_ms: int = Field(ge=0)
    expires_at_ms: int = Field(gt=0)
    opaque_binding: str = Field(min_length=1, max_length=131_072, repr=False)

