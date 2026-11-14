"""Person face profile: one reference photo, and recognition the Owner turns on.

Storing a photo grants no recognition capability. Recognition is a separate
choice with its own consent: only then is a feature derived from the photo, and
only people with one are ever compared with a camera frame. A face match is
resemblance for addressing someone, never authentication or a memory grant.
"""
from typing import Annotated, Literal

from pydantic import Field, model_validator

from .person import PersonContract

MAX_FACE_RECOGNITION_PERSONS = 25
MAX_FACE_TEMPLATES = 5
FACE_FEATURE_SCHEMA_VERSION = 1
#: Why a reference photo cannot be used for recognition.
FACE_ENROLLMENT_REJECTIONS = ("no_face", "multiple_faces", "face_too_small", "low_confidence")


class FaceRecognitionConsent(PersonContract):
    """The Owner's explicit, separate agreement to derive a face feature.

    ``attested`` is the Owner stating, in the phone app, that the person in the
    photo agreed. ``statement`` is the text the Owner was shown, kept so the
    record says what was agreed to and not only that something was.
    """

    consent_version: str = Field(min_length=1, max_length=64)
    statement: str = Field(min_length=1, max_length=1000)
    attested: Literal[True]
    # Stamped by the Host when it records the consent; ignored on requests.
    accepted_at: str | None = None


class PersonFaceState(PersonContract):
    schema_version: Literal[1] = 1
    person_id: str
    revision: int = Field(ge=0)
    has_image: bool
    sha256: str | None = None
    content_type: Literal["image/jpeg"] | None = None
    # enabled: consent recorded and a feature exists for the current photo.
    recognition_state: Literal["not_configured", "enabled"] = "not_configured"
    model_id: str | None = None
    preprocessing_version: str | None = None
    feature_schema_version: int | None = None
    recognition_consent_version: str | None = None
    recognition_enabled_at: str | None = None


class PersonFaceUpdate(PersonContract):
    expected_revision: int = Field(ge=0, strict=True)
    image_base64: str = Field(min_length=1, max_length=1398104)


class PersonFaceImage(PersonContract):
    revision: int = Field(ge=0)
    image_base64: str | None = None
    content_type: Literal["image/jpeg"] | None = None


class PersonFaceRecognitionEnable(PersonContract):
    """Owner request: use this Person's current photo for recognition."""

    expected_revision: int = Field(ge=1, strict=True)
    consent: FaceRecognitionConsent


class FaceFeatures(PersonContract):
    """What a face model made of one photo. Never shown, logged or sent to a model."""

    model_id: str = Field(min_length=1, max_length=128)
    weights_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    preprocessing_version: str = Field(min_length=1, max_length=128)
    feature_schema_version: Literal[1] = FACE_FEATURE_SCHEMA_VERSION
    vector: list[Annotated[float, Field(ge=-1e6, le=1e6, allow_inf_nan=False)]] = Field(
        min_length=2, max_length=2048
    )


class PersonFaceFeaturesWrite(PersonContract):
    """Host-internal: the consent together with the feature it authorizes.

    Bound to the photo revision the feature was derived from; a photo replaced
    in the meantime refuses the write.
    """

    expected_revision: int = Field(ge=1, strict=True)
    consent: FaceRecognitionConsent
    features: FaceFeatures


class FaceTemplate(PersonContract):
    # The photo revision the feature came from.
    revision: int = Field(ge=1)
    features: FaceFeatures


class FaceCandidate(PersonContract):
    person_id: str = Field(min_length=1, max_length=64)
    # What to call this person aloud (``person.address_as``), already chosen.
    address_as: str = Field(min_length=1, max_length=128)
    templates: list[FaceTemplate] = Field(min_length=1, max_length=MAX_FACE_TEMPLATES)


class FaceCandidates(PersonContract):
    """Every active Person of one Owner whose face recognition is enabled."""

    owner_id: str = Field(min_length=1)
    revision: str = Field(pattern=r"^[a-f0-9]{64}$")
    persons: list[FaceCandidate] = Field(
        default_factory=list, max_length=MAX_FACE_RECOGNITION_PERSONS
    )

    @model_validator(mode="after")
    def distinct_persons(self):
        if len({p.person_id for p in self.persons}) != len(self.persons):
            raise ValueError("a person appears once among the candidates")
        return self
