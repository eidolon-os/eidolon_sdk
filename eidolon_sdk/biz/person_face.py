"""Person photo management; storing a photo grants no recognition capability."""
from typing import Literal
from pydantic import Field
from .person import PersonContract

class PersonFaceState(PersonContract):
    schema_version: Literal[1] = 1
    person_id: str
    revision: int = Field(ge=0)
    has_image: bool
    sha256: str | None = None
    content_type: Literal["image/jpeg"] | None = None
    recognition_state: Literal["not_configured"] = "not_configured"
    model_id: str | None = None
    preprocessing_version: str | None = None
    feature_schema_version: int | None = None

class PersonFaceUpdate(PersonContract):
    expected_revision: int = Field(ge=0, strict=True)
    image_base64: str = Field(min_length=1, max_length=1398104)

class PersonFaceImage(PersonContract):
    revision: int = Field(ge=0)
    image_base64: str | None = None
    content_type: Literal["image/jpeg"] | None = None
