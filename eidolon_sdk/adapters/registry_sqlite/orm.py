"""SQLAlchemy rows for the registry SQLite adapter."""

from __future__ import annotations

from sqlalchemy import Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from eidolon_sdk.db.schema import EidolonBase


class RegistryBase(EidolonBase):
    __abstract__ = True


class TenantRow(RegistryBase):
    __tablename__ = "tenants"

    tenant_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)


class UserRow(RegistryBase):
    __tablename__ = "users"

    user_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    active_agent_id: Mapped[str | None] = mapped_column(String(64))
    display_name: Mapped[str] = mapped_column(
        String(128), nullable=False, default="", server_default=""
    )
    enabled: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    palace_path: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=""
    )
    memory_port: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    consolidator_enabled: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    consolidator_interval_hours: Mapped[float] = mapped_column(
        nullable=False, default=6.0, server_default="6.0"
    )
    consolidator_window_days: Mapped[int] = mapped_column(
        Integer, nullable=False, default=30, server_default="30"
    )
    consolidator_min_drawers: Mapped[int] = mapped_column(
        Integer, nullable=False, default=3, server_default="3"
    )
    consolidator_min_confidence: Mapped[float] = mapped_column(
        nullable=False, default=0.6, server_default="0.6"
    )
    created_at: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=""
    )


class DeviceRow(RegistryBase):
    __tablename__ = "devices"

    device_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False, default="", server_default="")
    kind: Mapped[str] = mapped_column(
        String(64), nullable=False, default="unknown", server_default="unknown"
    )
    enabled: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    psk_hash: Mapped[str | None] = mapped_column(Text)
    paired: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    approved: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    approved_at: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=""
    )
    last_seen: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=""
    )
    metadata_json: Mapped[str] = mapped_column(
        Text, nullable=False, default="{}", server_default="{}"
    )


class DeviceBindingRow(RegistryBase):
    __tablename__ = "device_bindings"

    device_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    agent_id: Mapped[str] = mapped_column(String(128), nullable=False)
    bound_at: Mapped[str] = mapped_column(Text, nullable=False)
    interaction_mode: Mapped[str | None] = mapped_column(String(32))


class AgentMetadataRow(RegistryBase):
    __tablename__ = "agent_metadata"

    agent_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    template_id: Mapped[str] = mapped_column(String(128), nullable=False)
    template_revision: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    display_name: Mapped[str] = mapped_column(
        String(128), nullable=False, default="", server_default=""
    )
    created_at: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=""
    )
