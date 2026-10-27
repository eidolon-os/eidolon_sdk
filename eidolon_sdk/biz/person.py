"""OS people: identity metadata, never an authentication or memory grant."""

from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field


class PersonContract(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class PersonProfile(PersonContract):
    """Explicitly supplied information only; inferred traits need a separate contract."""

    schema_version: Literal[1] = 1
    preferred_name: str = Field(default="", max_length=128)
    language: str = Field(default="", max_length=64)
    description: str = Field(default="", max_length=2000)
    preferences: list[Annotated[str, Field(min_length=1, max_length=256)]] = Field(
        default_factory=list, max_length=32
    )


class PersonCreate(PersonContract):
    person_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    display_name: str = Field(min_length=1, max_length=128)
    profile: PersonProfile = Field(default_factory=PersonProfile)


class PersonUpdate(PersonContract):
    expected_revision: int = Field(ge=1)
    display_name: str = Field(min_length=1, max_length=128)
    status: Literal["active", "inactive"]
    profile: PersonProfile


class PersonView(PersonContract):
    person_id: str
    owner_id: str
    display_name: str
    status: Literal["active", "inactive"]
    revision: int
    profile: PersonProfile


class PersonCollection(PersonContract):
    persons: list[PersonView] = Field(default_factory=list)


class PersonDeletion(PersonContract):
    deleted: Literal[True] = True
