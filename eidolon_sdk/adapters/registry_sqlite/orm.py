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
