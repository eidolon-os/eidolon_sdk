"""Typed consumer view of the System Data Runtime Snapshot V1 contract."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from eidolon_sdk.biz.persona import ResolvedRuntimeIdentity


class MemoryRealmSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    realm_id: str = Field(min_length=1, max_length=64)
    lifecycle_state: Literal["active"]


class PersonalMemoryRealmSnapshot(BaseModel):
    """Data catalog binding, not a user authorization credential."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    realm_id: str = Field(min_length=1, max_length=64)
    owner_id: str = Field(min_length=1, max_length=64)
    person_id: str = Field(min_length=1, max_length=64)
    person_revision: int = Field(ge=1, strict=True)
    status: Literal["active"]


class ProvisionalMemoryPolicy(BaseModel):
    """Independent Owner controls; neither permits ordinary private-memory recall."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    save_allowed: bool = Field(default=False, strict=True)
    session_recall_allowed: bool = Field(default=False, strict=True)


class ProvisionalMemoryPolicyState(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    owner_id: str = Field(min_length=1, max_length=64)
    person_id: str = Field(min_length=1, max_length=64)
    person_revision: int = Field(ge=1, strict=True)
    realm_id: str = Field(min_length=1, max_length=64)
    policy: ProvisionalMemoryPolicy


class ProvisionalMemoryAccessSnapshot(ProvisionalMemoryPolicyState):
    """Current catalog policy for this session, not identity proof or runner readiness."""

    session_id: str = Field(min_length=1, max_length=256, pattern=r"\S")
    scope: Literal["provisional_session"] = "provisional_session"


class PersonalMemoryState(BaseModel):
    """Owner management state; never a runtime memory access grant."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    owner_id: str
    person_id: str
    person_revision: int = Field(ge=1, strict=True)
    person_status: Literal["active", "inactive"]
    realm_id: str | None = None
    state: Literal["unbound", "active", "inactive"]


class PersonaGenomeSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    genome_id: str = Field(min_length=1, max_length=64)
    version: int = Field(ge=1)
    lifecycle_state: Literal["committed"]
    schema_version: str = Field(min_length=1, max_length=64)
    genome_hash: str = Field(min_length=1, max_length=80)
    realizer_version: str = Field(min_length=1, max_length=64)
    genome: dict[str, Any]


class CompanionRuntimeSnapshot(BaseModel):
    """Ready-to-run, immutable-at-read Companion authority snapshot."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    contract_version: Literal["1"]
    operation: Literal["companion.runtime-snapshot"]
    owner_id: str = Field(min_length=1, max_length=64)
    companion_id: str = Field(min_length=1, max_length=64)
    lifecycle_state: Literal["active"]
    runtime_config: dict[str, Any]
    memory_realm: MemoryRealmSnapshot
    persona_genome: PersonaGenomeSnapshot

    def runtime_identity(self, *, device_id: str | None = None) -> ResolvedRuntimeIdentity:
        """Map the wire DTO to the shared runtime domain value."""

        genome = self.persona_genome
        return ResolvedRuntimeIdentity(
            owner_id=self.owner_id,
            companion_id=self.companion_id,
            device_id=device_id,
            memory_realm_id=self.memory_realm.realm_id,
            genome_id=genome.genome_id,
            schema_version=genome.schema_version,
            genome_hash=genome.genome_hash,
            realizer_version=genome.realizer_version,
        )


__all__ = [
    "CompanionRuntimeSnapshot",
    "MemoryRealmSnapshot",
    "PersonaGenomeSnapshot",
]
