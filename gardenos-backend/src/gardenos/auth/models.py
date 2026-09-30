from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Identity,
    Index,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from gardenos.shared.db import Base, IdMixin, TimestampMixin

if TYPE_CHECKING:
    from gardenos.organization.models import Employee


class User(IdMixin, TimestampMixin, Base):
    """A person. Not tenant-owned: one user can be an employee of several companies."""

    __tablename__ = "users"  # "user" is a reserved word in PostgreSQL

    name: Mapped[str | None] = mapped_column(String)
    surname: Mapped[str | None] = mapped_column(String)
    username: Mapped[str | None] = mapped_column(String, unique=True)
    location: Mapped[str | None] = mapped_column(String)

    # uselist=False -> scalar (1:1). passive_deletes=True -> let the database's
    # ON DELETE CASCADE do the work instead of SQLAlchemy loading children first.
    auth: Mapped[Auth | None] = relationship(
        back_populates="user", uselist=False, passive_deletes=True
    )
    employments: Mapped[list[Employee]] = relationship(
        back_populates="user", passive_deletes=True
    )
    refresh_tokens: Mapped[list[RefreshToken]] = relationship(
        back_populates="user", passive_deletes=True
    )
    one_time_tokens: Mapped[list[UserToken]] = relationship(
        back_populates="user", passive_deletes=True
    )


class Auth(IdMixin, TimestampMixin, Base):
    """Credentials, kept apart from the profile so password_hash is rarely loaded."""

    __tablename__ = "auth"

    # unique=True makes the User <-> Auth relationship strictly 1:1
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), unique=True
    )
    # Must be stored lowercased (see the CHECK below), which makes the unique
    # constraint effectively case-insensitive. Normalize in the application.
    email: Mapped[str | None] = mapped_column(String, unique=True)
    password_hash: Mapped[str | None] = mapped_column(String)
    is_active: Mapped[bool | None] = mapped_column(
        Boolean, server_default=text("true")
    )
    is_verified: Mapped[bool | None] = mapped_column(
        Boolean, server_default=text("false")
    )
    last_login: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("email = lower(email)", name="email_lowercase"),
    )

    user: Mapped[User] = relationship(back_populates="auth")


class RefreshToken(Base):
    """Long-lived, revocable session token. Only its HASH is stored.

    The raw token is a high-entropy random string shown to the client once;
    a fast hash (e.g. SHA-256) is enough here, unlike passwords, because the
    token is not guessable.

    Rotation with reuse detection: each refresh revokes the presented row and
    inserts a new one in the same `family_id`. Presenting an already-revoked
    token means it was stolen -> revoke the whole family.
    Not exposed by the API, so it has no public_id.
    """

    __tablename__ = "refresh_token"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[str] = mapped_column(String, unique=True)
    family_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    user: Mapped[User] = relationship(back_populates="refresh_tokens")


class TokenPurpose(enum.StrEnum):
    EMAIL_VERIFICATION = "email_verification"
    PASSWORD_RESET = "password_reset"


class UserToken(Base):
    """Single-use token emailed to a user (verify email / reset password).
    Only the HASH is stored. `used_at` marks it consumed; `expires_at` bounds it."""

    __tablename__ = "user_token"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE")
    )
    purpose: Mapped[TokenPurpose] = mapped_column(
        Enum(
            TokenPurpose,
            native_enum=False,
            length=30,
            create_constraint=False,  # explicit CHECK below (avoids duplicate in autogenerate)
            name="token_purpose",
            values_callable=lambda e: [m.value for m in e],
        )
    )
    token_hash: Mapped[str] = mapped_column(String, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        Index("ix_user_token_user_id_purpose", "user_id", "purpose"),
        CheckConstraint(
            "purpose IN ('email_verification', 'password_reset')",
            name="purpose_valid",
        ),
    )

    user: Mapped[User] = relationship(back_populates="one_time_tokens")
