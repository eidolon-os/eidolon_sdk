"""Typed consumer view of the System Data Runtime Snapshot V1 contract."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from eidolon_sdk.biz.persona import ResolvedRuntimeIdentity


class MemoryRealmSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    realm_id: str = Field(min_length=1, max_length=64)
    lifecycle_state: Literal["active"]


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
