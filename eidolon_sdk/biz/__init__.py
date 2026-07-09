"""Shared Eidolon business contracts."""

from .persona import (
    PERSONA_COMPILER_VERSION,
    PERSONA_GENOME_SCHEMA_VERSION,
    PersonaEvolutionProposalEvent,
    PersonaGenomeV1,
    PersonaObservationEvent,
    PersonaTraitState,
    ResolvedRuntimeIdentity,
    normalize_persona_genome,
    persona_genome_hash,
    persona_genome_to_json,
)

__all__ = [
    "PERSONA_COMPILER_VERSION",
    "PERSONA_GENOME_SCHEMA_VERSION",
    "PersonaEvolutionProposalEvent",
    "PersonaGenomeV1",
    "PersonaObservationEvent",
    "PersonaTraitState",
    "ResolvedRuntimeIdentity",
    "normalize_persona_genome",
    "persona_genome_hash",
    "persona_genome_to_json",
]
