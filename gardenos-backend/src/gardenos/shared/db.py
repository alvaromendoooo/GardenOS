"""Declarative base and column mixins shared by every module's models."""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Identity, MetaData, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Deterministic constraint names. Without this, Postgres generates names that
# Alembic cannot reliably reference when you later alter or drop a constraint.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class IdMixin:
    """Internal bigint PK (never exposed by the API) + public UUID (exposed)."""

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    public_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        unique=True,
        server_default=func.gen_random_uuid(),
    )


class TimestampMixin:
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    # server_default covers INSERT; onupdate is applied by SQLAlchemy on UPDATE
    # (raw SQL updates bypass it - a DB trigger would be the stricter option).
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
