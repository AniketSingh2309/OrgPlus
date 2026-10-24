"""Database schema. Every table carries tenant_id so we can go multi-tenant later.

Google object ids (users, groups, org units, devices) are globally unique, so
they are used directly as primary keys.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    Float,
    ForeignKey,
    Index,
    MetaData,
    SmallInteger,
    Text,
    UniqueConstraint,
    false,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

EMPTY_JSON = text("'{}'::jsonb")
EMPTY_ARRAY = text("'{}'::text[]")


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    type_annotation_map = {  # noqa: RUF012  (SQLAlchemy-documented pattern)
        str: Text(),
        datetime: DateTime(timezone=True),
        dict[str, Any]: JSONB(),
        list[str]: ARRAY(Text()),
    }


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    name: Mapped[str]
    domain: Mapped[str] = mapped_column(unique=True)
    customer_id: Mapped[str] = mapped_column(server_default="my_customer")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class TenantScoped:
    """Mixin: tenant_id on every table. Indexes lead with tenant_id where needed."""

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE")
    )


class OrgUnit(TenantScoped, Base):
    __tablename__ = "org_units"
    __table_args__ = (UniqueConstraint("tenant_id", "path"),)

    id: Mapped[str] = mapped_column(primary_key=True)  # orgUnitId, e.g. "id:03ph8a2z..."
    name: Mapped[str]
    path: Mapped[str]
    parent_path: Mapped[str | None]
    description: Mapped[str | None]
    synced_at: Mapped[datetime] = mapped_column(server_default=func.now())


class User(TenantScoped, Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("tenant_id", "primary_email"),
        Index("ix_users_tenant_org_unit", "tenant_id", "org_unit_path"),
        Index("ix_users_tenant_department", "tenant_id", "department"),
    )

    id: Mapped[str] = mapped_column(primary_key=True)  # Google user id (= profileId in reports)
    primary_email: Mapped[str]
    full_name: Mapped[str | None]
    given_name: Mapped[str | None]
    family_name: Mapped[str | None]
    org_unit_path: Mapped[str | None]
    department: Mapped[str | None]
    title: Mapped[str | None]
    manager_email: Mapped[str | None]
    is_admin: Mapped[bool] = mapped_column(server_default=false())
    is_delegated_admin: Mapped[bool] = mapped_column(server_default=false())
    admin_role: Mapped[str | None]  # from roleAssignments + roles
    suspended: Mapped[bool] = mapped_column(server_default=false())
    suspension_reason: Mapped[str | None]
    archived: Mapped[bool] = mapped_column(server_default=false())
    is_enrolled_in_2sv: Mapped[bool] = mapped_column(server_default=false())
    is_enforced_in_2sv: Mapped[bool] = mapped_column(server_default=false())
    creation_time: Mapped[datetime | None]
    last_login_time: Mapped[datetime | None]
    thumbnail_photo_url: Mapped[str | None]
    aliases: Mapped[list[str]] = mapped_column(server_default=EMPTY_ARRAY)
    raw: Mapped[dict[str, Any]] = mapped_column(server_default=EMPTY_JSON)
    synced_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Group(TenantScoped, Base):
    __tablename__ = "groups"
    __table_args__ = (UniqueConstraint("tenant_id", "email"),)

    id: Mapped[str] = mapped_column(primary_key=True)
    email: Mapped[str]
    name: Mapped[str | None]
    description: Mapped[str | None]
    direct_members_count: Mapped[int | None]
    admin_created: Mapped[bool] = mapped_column(server_default=false())
    raw: Mapped[dict[str, Any]] = mapped_column(server_default=EMPTY_JSON)
    synced_at: Mapped[datetime] = mapped_column(server_default=func.now())


class GroupMember(TenantScoped, Base):
    __tablename__ = "group_members"
    __table_args__ = (Index("ix_group_members_tenant_email", "tenant_id", "email"),)

    group_id: Mapped[str] = mapped_column(
        ForeignKey("groups.id", ondelete="CASCADE"), primary_key=True
    )
    member_id: Mapped[str] = mapped_column(primary_key=True)
    email: Mapped[str | None]
    role: Mapped[str | None]  # OWNER / MANAGER / MEMBER
    type: Mapped[str | None]  # USER / GROUP / CUSTOMER / EXTERNAL
    status: Mapped[str | None]
    synced_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Device(TenantScoped, Base):
    __tablename__ = "devices"
    __table_args__ = (Index("ix_devices_tenant_user_email", "tenant_id", "user_email"),)

    kind: Mapped[str] = mapped_column(primary_key=True)  # "mobile" | "chromeos"
    id: Mapped[str] = mapped_column(primary_key=True)  # resourceId / deviceId
    user_email: Mapped[str | None]
    model: Mapped[str | None]
    os: Mapped[str | None]
    os_version: Mapped[str | None]
    status: Mapped[str | None]
    device_type: Mapped[str | None]
    serial_number: Mapped[str | None]
    first_sync: Mapped[datetime | None]
    last_sync: Mapped[datetime | None]
    raw: Mapped[dict[str, Any]] = mapped_column(server_default=EMPTY_JSON)
    synced_at: Mapped[datetime] = mapped_column(server_default=func.now())


class AppToken(TenantScoped, Base):
    __tablename__ = "app_tokens"
    __table_args__ = (Index("ix_app_tokens_tenant_client", "tenant_id", "client_id"),)

    user_id: Mapped[str] = mapped_column(primary_key=True)
    client_id: Mapped[str] = mapped_column(primary_key=True)
    user_email: Mapped[str | None]
    display_text: Mapped[str | None]
    scopes: Mapped[list[str]] = mapped_column(server_default=EMPTY_ARRAY)
    anonymous: Mapped[bool] = mapped_column(server_default=false())
    native_app: Mapped[bool] = mapped_column(server_default=false())
    risk: Mapped[str | None]  # high / medium / low, computed at sync time
    raw: Mapped[dict[str, Any]] = mapped_column(server_default=EMPTY_JSON)
    synced_at: Mapped[datetime] = mapped_column(server_default=func.now())


class DailyUsage(TenantScoped, Base):
    """One row per user, day and metric (dc, de, dv, es, er, mt, mm, ch, cal, ...)."""

    __tablename__ = "daily_usage"
    __table_args__ = (Index("ix_daily_usage_tenant_date", "tenant_id", "date"),)

    # tenant_id is part of the key: (tenant_id, user_id, date, metric)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[str] = mapped_column(primary_key=True)
    date: Mapped[date] = mapped_column(primary_key=True)
    metric: Mapped[str] = mapped_column(primary_key=True)
    user_email: Mapped[str | None]
    value: Mapped[float] = mapped_column(Float)


class Event(TenantScoped, Base):
    """One row per event inside a Reports API activity (an activity can hold several)."""

    __tablename__ = "events"
    __table_args__ = (
        UniqueConstraint("tenant_id", "app", "time", "unique_qualifier", "event_seq"),
        Index("ix_events_tenant_user_time", "tenant_id", "user_email", "time"),
        Index("ix_events_tenant_app_name_time", "tenant_id", "app", "event_name", "time"),
        Index("ix_events_params_gin", "params", postgresql_using="gin"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    app: Mapped[str]
    time: Mapped[datetime]
    unique_qualifier: Mapped[str]  # activity id.uniqueQualifier
    event_seq: Mapped[int] = mapped_column(SmallInteger)  # index within activity.events
    event_name: Mapped[str]
    event_type: Mapped[str | None]
    user_email: Mapped[str | None]
    user_id: Mapped[str | None]  # actor.profileId
    ip: Mapped[str | None]
    doc_id: Mapped[str | None]
    doc_title: Mapped[str | None]
    doc_type: Mapped[str | None]
    visibility: Mapped[str | None]
    is_external: Mapped[bool | None]
    # Location: Reports networkInfo.regionCode, else GeoLite2 lookup on the IP.
    country: Mapped[str | None]
    city: Mapped[str | None]
    lat: Mapped[float | None] = mapped_column(Float)
    lon: Mapped[float | None] = mapped_column(Float)
    params: Mapped[dict[str, Any]] = mapped_column(server_default=EMPTY_JSON)


class SyncState(TenantScoped, Base):
    """Per-tenant cursor for each sync job (e.g. "events:login", "usage", "directory")."""

    __tablename__ = "sync_state"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True
    )
    key: Mapped[str] = mapped_column(primary_key=True)
    cursor_time: Mapped[datetime | None]
    last_run_at: Mapped[datetime | None]
    last_success_at: Mapped[datetime | None]
    status: Mapped[str | None]  # running / ok / error
    error: Mapped[str | None]
    detail: Mapped[dict[str, Any]] = mapped_column(server_default=EMPTY_JSON)


class ScoreWeight(TenantScoped, Base):
    __tablename__ = "score_weights"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True
    )
    metric: Mapped[str] = mapped_column(primary_key=True)
    weight: Mapped[float] = mapped_column(Float)
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_by: Mapped[str | None]


class AuditView(TenantScoped, Base):
    """Who looked at whose profile, and when."""

    __tablename__ = "audit_views"
    __table_args__ = (Index("ix_audit_views_tenant_at", "tenant_id", "at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    viewer: Mapped[str]
    viewed_user: Mapped[str]
    at: Mapped[datetime] = mapped_column(server_default=func.now())


# --- Part 2: connection, plan detection, capabilities -----------------------------------


class TenantCredential(Base):
    """Encrypted service-account key plus connection details. Never sent to the frontend."""

    __tablename__ = "tenant_credentials"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True
    )
    sa_json_enc: Mapped[str]
    admin_email: Mapped[str]
    client_email: Mapped[str | None]
    client_id: Mapped[str | None]
    bigquery_project: Mapped[str | None]
    bigquery_dataset: Mapped[str | None]
    scope_check: Mapped[dict[str, Any]] = mapped_column(server_default=EMPTY_JSON)
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now())


class TenantPlan(Base):
    __tablename__ = "tenant_plan"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True
    )
    edition: Mapped[str]  # e.g. "Business Standard", or "Unknown"
    tier: Mapped[str]  # free / plus / enterprise / unknown
    sku_breakdown: Mapped[dict[str, Any]] = mapped_column(server_default=EMPTY_JSON)
    licences_total: Mapped[int | None]
    licences_assigned: Mapped[int | None]
    licensing_error: Mapped[str | None]
    detected_at: Mapped[datetime] = mapped_column(server_default=func.now())


class TenantCapability(Base):
    __tablename__ = "tenant_capabilities"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True
    )
    key: Mapped[str] = mapped_column(primary_key=True)
    status: Mapped[str]  # on / locked / error / not_configured
    detail: Mapped[str | None]
    detected_at: Mapped[datetime] = mapped_column(server_default=func.now())


class CapabilityChange(TenantScoped, Base):
    """A capability flipped between detections (upgrade/downgrade). Drives the banner."""

    __tablename__ = "capability_changes"
    __table_args__ = (Index("ix_capability_changes_tenant_at", "tenant_id", "at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    key: Mapped[str]
    old_status: Mapped[str | None]
    new_status: Mapped[str]
    acknowledged: Mapped[bool] = mapped_column(server_default=false())
    at: Mapped[datetime] = mapped_column(server_default=func.now())


class TenantSettings(Base):
    __tablename__ = "tenant_settings"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True
    )
    licence_price_inr: Mapped[float] = mapped_column(Float, server_default=text("0"))
    licences_purchased: Mapped[int | None]  # Licensing API only reports assignments
    work_start: Mapped[str] = mapped_column(server_default="09:00")
    work_end: Mapped[str] = mapped_column(server_default="19:00")
    timezone: Mapped[str] = mapped_column(server_default="Asia/Kolkata")
    hide_locked: Mapped[bool] = mapped_column(server_default=false())
    digest_recipients: Mapped[list[str]] = mapped_column(server_default=EMPTY_ARRAY)
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now())


class LicenceAssignment(TenantScoped, Base):
    __tablename__ = "licence_assignments"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True
    )
    user_email: Mapped[str] = mapped_column(primary_key=True)
    sku_id: Mapped[str] = mapped_column(primary_key=True)
    product_id: Mapped[str]
    sku_name: Mapped[str | None]
    synced_at: Mapped[datetime] = mapped_column(server_default=func.now())


class SharedDrive(TenantScoped, Base):
    __tablename__ = "shared_drives"

    id: Mapped[str] = mapped_column(primary_key=True)
    name: Mapped[str]
    created_time: Mapped[datetime | None]
    hidden: Mapped[bool] = mapped_column(server_default=false())
    member_count: Mapped[int | None]
    external_member_count: Mapped[int | None]
    members: Mapped[dict[str, Any]] = mapped_column(server_default=EMPTY_JSON)  # {"items": [...]}
    restrictions: Mapped[dict[str, Any]] = mapped_column(server_default=EMPTY_JSON)
    synced_at: Mapped[datetime] = mapped_column(server_default=func.now())


class ModuleData(Base):
    """Small per-module snapshots for paid modules (vault matters, alerts, chrome reports)."""

    __tablename__ = "module_data"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True
    )
    module: Mapped[str] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(primary_key=True)
    data: Mapped[dict[str, Any]] = mapped_column(server_default=EMPTY_JSON)
    synced_at: Mapped[datetime] = mapped_column(server_default=func.now())
