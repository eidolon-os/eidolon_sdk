"""Which model tools a Companion may use, and the catalog they are chosen from.

Two Owner-held layers decide it, both kept by System Data:

- the Owner's tool policy: one switch per tool, for every Companion;
- each Companion's own switches, which can only narrow the Owner's.

A tool is granted when neither layer turns it off and it is not reserved by the
system. Defaults come from the catalog, so a tool nobody has touched behaves the
way it did before any switch existed. A Companion's ``allow_body_control`` is
the master switch over every tool that moves or tunes its body; turning it off
leaves the Companion's per-tool choices as they were.

The catalog is published by the Agent, the only process that assembles a turn's
tools. What a device, its Owner's output policy and the Host's configuration
allow at run time is a separate question this module never answers: granting a
tool lets a session use it where it is available, nothing more.
"""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StringConstraints, model_validator

from eidolon_sdk.biz.capabilities import digest

ToolKey = Annotated[
    str,
    StringConstraints(pattern=r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*$", max_length=128),
]
MAX_OVERRIDES = 256

#: Why a tool is unavailable to one Companion, in the order the layers apply.
BlockedBy = Literal["reserved", "global", "body_control", "companion"]


class _Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ToolPolicy(_Contract):
    """The Owner's switches: an override per tool, absent meaning the default."""

    revision: int = Field(default=0, ge=0, strict=True)
    overrides: dict[ToolKey, StrictBool] = Field(default_factory=dict, max_length=MAX_OVERRIDES)


class CompanionToolPolicy(ToolPolicy):
    """One Companion's switches, inside what the Owner's allow."""

    allow_body_control: bool = Field(default=True, strict=True)


class ToolPolicyChange(_Contract):
    """Changes to one layer, checked against the revision the writer read.

    ``None`` removes an override, returning the tool to its default. Carrying
    only what changed keeps one switch from overwriting another just changed.
    """

    expected_revision: int = Field(ge=0, strict=True)
    changes: dict[ToolKey, StrictBool | None] = Field(default_factory=dict, max_length=MAX_OVERRIDES)
    #: The Companion layer's master switch over body tools; unknown to the Owner's.
    allow_body_control: bool | None = Field(default=None, strict=True)

    @model_validator(mode="after")
    def _not_empty(self) -> Self:
        if not self.changes and self.allow_body_control is None:
            raise ValueError("a tool policy change must change something")
        return self


def apply_changes[P: ToolPolicy](policy: P, change: ToolPolicyChange) -> P:
    """The policy after ``change``; the same object when nothing differs.

    The caller compares ``change.expected_revision`` with the stored revision
    inside its own transaction; this only computes the next value.
    """

    if change.allow_body_control is not None and not isinstance(policy, CompanionToolPolicy):
        raise ValueError("allow_body_control belongs to a Companion's tool policy")
    overrides = dict(policy.overrides)
    for key, value in change.changes.items():
        if value is None:
            overrides.pop(key, None)
        else:
            overrides[key] = value
    update: dict = {"overrides": overrides}
    if change.allow_body_control is not None:
        update["allow_body_control"] = change.allow_body_control
    if all(getattr(policy, field) == value for field, value in update.items()):
        return policy
    return type(policy).model_validate(
        {**policy.model_dump(), **update, "revision": policy.revision + 1}
    )


class CompanionToolPolicyState(_Contract):
    """One Companion's switches, as System Data holds them."""

    companion_id: str = Field(min_length=1, max_length=64)
    lifecycle_state: str = Field(min_length=1, max_length=32)
    policy: CompanionToolPolicy


class OwnerToolPolicyState(_Contract):
    """The Owner's switches and those of every Companion it keeps."""

    owner_id: str = Field(min_length=1, max_length=64)
    policy: ToolPolicy
    companions: tuple[CompanionToolPolicyState, ...] = ()


class ToolPresentation(_Contract):
    """What the Owner reads about a tool: its name, one sentence, its group."""

    label: str = Field(min_length=1, max_length=64)
    summary: str = Field(min_length=1, max_length=256)
    group: str = Field(pattern=r"^[a-z][a-z0-9_]*$", max_length=32)
    #: The Host service the tool runs on, which must be set up for it to work.
    host_feature: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_]*$", max_length=32)


class ToolRequirements(_Contract):
    """What a session needs before this tool is offered, as the Agent decides it.

    Every field restates an existing gate, never a new rule: a contract's
    required output or input, the contracts the device must declare, the head
    profile ``stackchan_head`` needs, and the Host feature that must be set up.
    """

    outputs: tuple[str, ...] = ()
    inputs: dict[str, str] = Field(default_factory=dict)
    device_contracts: tuple[str, ...] = ()
    motion_profile: str | None = None
    host_feature: str | None = None


class ToolReservation(_Contract):
    #: Interactive sessions never offer it (Owner-wide side channels).
    reason: Literal["interactive_session"]


class ToolCatalogEntry(_Contract):
    key: ToolKey
    label: str = Field(min_length=1, max_length=128)
    summary: str = Field(default="", max_length=256)
    group: str = Field(pattern=r"^[a-z][a-z0-9_]*$", max_length=32)
    #: brain: needs no device; channel: runs in the Channel; device: runs on
    #: the device; agent_device: the Agent's own tool that needs a device fact.
    kind: Literal["brain", "channel", "device", "agent_device"]
    side_effect: bool
    #: Governed by a Companion's ``allow_body_control`` as well as its switch.
    body_control: bool = False
    default_enabled: bool = True
    reserved: ToolReservation | None = None
    requires: ToolRequirements = Field(default_factory=ToolRequirements)
    #: Whether this Host has what the tool needs, when the Agent can tell.
    host_available: bool | None = None


class ToolCatalog(_Contract):
    catalog_revision: str = Field(min_length=1, max_length=80)
    tools: tuple[ToolCatalogEntry, ...]

    @classmethod
    def of(cls, entries) -> ToolCatalog:
        tools = tuple(sorted(entries, key=lambda entry: entry.key))
        if len({entry.key for entry in tools}) != len(tools):
            raise ValueError("duplicate tool in catalog")
        return cls(
            catalog_revision=digest([entry.model_dump(mode="json") for entry in tools]),
            tools=tools,
        )

    def entry(self, key: str) -> ToolCatalogEntry | None:
        return next((entry for entry in self.tools if entry.key == key), None)


class DeviceToolOffer(_Contract):
    """What one device's channel offers a session, as the Channel Provider granted it.

    Two facts side by side, so a reader can tell "the device cannot" from "the
    Owner has not allowed it": what the Manifest declared, and what the current
    output policy lets a session use of that. Read from the channel's grant,
    never recomputed elsewhere.
    """

    operation: Literal["channel.device-offer"] = "channel.device-offer"
    device_id: str = Field(min_length=1, max_length=128)
    #: Installed device contracts the accepted Manifest declares.
    declared_capabilities: tuple[str, ...] = ()
    #: The head profile the Manifest declares, whatever the Owner selected.
    declared_motion_profile: str | None = None
    #: None until the Owner has decided this device's outputs.
    policy_revision: int | None = Field(default=None, ge=1)
    outputs: dict[str, bool] | None = None
    #: The device contracts a session on this channel may use.
    session_capabilities: tuple[str, ...] = ()


def _switch(policy: ToolPolicy, entry: ToolCatalogEntry) -> bool:
    return policy.overrides.get(entry.key, entry.default_enabled)


def blocked_by(
    entry: ToolCatalogEntry,
    owner: ToolPolicy | None,
    companion: CompanionToolPolicy | None,
) -> BlockedBy | None:
    """The first layer that keeps this tool from this Companion, or None."""

    owner = owner or ToolPolicy()
    companion = companion or CompanionToolPolicy()
    if entry.reserved is not None:
        return "reserved"
    if not _switch(owner, entry):
        return "global"
    if entry.body_control and not companion.allow_body_control:
        return "body_control"
    if not _switch(companion, entry):
        return "companion"
    return None


def granted(
    catalog: ToolCatalog,
    owner: ToolPolicy | None,
    companion: CompanionToolPolicy | None,
) -> frozenset[str]:
    """The catalog keys this Companion may use: the one rule every reader shares."""

    return frozenset(
        entry.key for entry in catalog.tools if blocked_by(entry, owner, companion) is None
    )


__all__ = [
    "BlockedBy",
    "CompanionToolPolicy",
    "CompanionToolPolicyState",
    "DeviceToolOffer",
    "OwnerToolPolicyState",
    "ToolCatalog",
    "ToolCatalogEntry",
    "ToolKey",
    "ToolPolicy",
    "ToolPolicyChange",
    "ToolPresentation",
    "ToolRequirements",
    "ToolReservation",
    "apply_changes",
    "blocked_by",
    "granted",
]
