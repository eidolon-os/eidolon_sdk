"""Advisory Person feedback on an existing session, never an authorization.

This transport contract separates the observed subject from a Person match.
Voice is the only enabled modality today; visual evidence can later describe a
visible person without being treated as the speaker. No embeddings or media
belong in this packet.
"""

from typing import Literal

from pydantic import Field, model_validator

from .person import PersonContract


class PersonObservationFeedback(PersonContract):
    schema_version: Literal[1] = 1
    sequence: int = Field(ge=1, strict=True)
    session_id: str = Field(min_length=1, max_length=128)
    conversation_id: str = Field(min_length=1, max_length=128)
    turn_id: str = Field(min_length=1, max_length=128)
    subject_role: Literal["speaker", "visible_person"] = "speaker"
    modalities: list[Literal["voice", "face"]] = Field(default_factory=lambda: ["voice"], min_length=1, max_length=2)
    status: Literal["identified", "unknown", "uncertain", "unavailable"]
    reason: str = Field(min_length=1, max_length=128)
    person_id: str | None = Field(default=None, min_length=1, max_length=64)
    display_name: str | None = Field(default=None, min_length=1, max_length=128)
    confidence: Literal["validated", "controlled_trial", "unvalidated", "none"]
    issued_at: float = Field(ge=0, allow_inf_nan=False)
    expires_at: float = Field(gt=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def coherent(self):
        if self.session_id != self.conversation_id:
            raise ValueError("feedback must address its source conversation")
        if not 0 < self.expires_at - self.issued_at <= 10:
            raise ValueError("feedback cannot extend the observation lease")
        if len(set(self.modalities)) != len(self.modalities):
            raise ValueError("duplicate modality")
        # Until an active-speaker association contract is implemented, a face
        # match can only describe a visible person, never grant speaker identity.
        if self.subject_role == "speaker" and self.modalities != ["voice"]:
            raise ValueError("visual speaker association is not enabled")
        if self.subject_role == "visible_person" and self.modalities != ["face"]:
            raise ValueError("visible person feedback requires visual evidence")
        if self.status == "identified":
            if not self.person_id or not self.display_name or self.confidence not in {"validated", "controlled_trial"}:
                raise ValueError("identified feedback requires a Person and a validated decision")
        elif self.person_id is not None or self.display_name is not None:
            raise ValueError("unresolved feedback cannot carry personal identity")
        return self
