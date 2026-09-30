from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, String, text
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


class Auth(IdMixin, TimestampMixin, Base):
    """Credentials, kept apart from the profile so password_hash is rarely loaded."""

    __tablename__ = "auth"

    # unique=True makes the User <-> Auth relationship strictly 1:1
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), unique=True
    )
    # Store emails lowercased (normalize in the application) so this unique
    # constraint is effectively case-insensitive.
    email: Mapped[str | None] = mapped_column(String, unique=True)
    password_hash: Mapped[str | None] = mapped_column(String)
    is_active: Mapped[bool | None] = mapped_column(
        Boolean, server_default=text("true")
    )
    is_verified: Mapped[bool | None] = mapped_column(
        Boolean, server_default=text("false")
    )
    last_login: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(back_populates="auth")
