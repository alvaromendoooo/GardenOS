"""Company (the tenant) and the people/teams inside it.

Tenant rule used across the whole schema: every tenant-owned table carries its
own company_id, and every FK to another tenant-owned table is a COMPOSITE FK
(x_id, company_id) -> x(id, company_id). The database then refuses a row that
points at another company's data, even if application code has a bug.

Relationship rule: relationships that follow a composite FK declare
`foreign_keys` and `primaryjoin` explicitly and use ONLY the single id column.
Otherwise SQLAlchemy would also try to write company_id from the parent row,
clashing with the company_id we set ourselves (and, for nullable links such as
employee.team_id, it would try to NULL a NOT NULL company_id).
"""

from __future__ import annotations

import enum
from datetime import datetime
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from gardenos.shared.db import Base, IdMixin, TimestampMixin

if TYPE_CHECKING:
    from gardenos.auth.models import User
    from gardenos.customer.models import Customer
    from gardenos.service.models import Service
    from gardenos.workorder.models import WorkOrder, WorkOrderPhoto


class Company(IdMixin, TimestampMixin, Base):
    __tablename__ = "company"

    name: Mapped[str | None] = mapped_column(String)
    location: Mapped[str | None] = mapped_column(String)
    # ISO 4217 code ("EUR", "USD"). All money of this company is in this currency.
    currency: Mapped[str | None] = mapped_column(String(3))
    # IANA timezone name ("Europe/Madrid", "America/New_York"). Schedule dates
    # and times are wall-clock values interpreted in this zone.
    timezone: Mapped[str | None] = mapped_column(String)
    file_report: Mapped[str | None] = mapped_column(String)

    teams: Mapped[list[Team]] = relationship(
        back_populates="company", passive_deletes=True
    )
    employees: Mapped[list[Employee]] = relationship(
        back_populates="company", passive_deletes=True
    )
    customers: Mapped[list[Customer]] = relationship(
        back_populates="company", passive_deletes=True
    )
    services: Mapped[list[Service]] = relationship(
        back_populates="company", passive_deletes=True
    )
    work_orders: Mapped[list[WorkOrder]] = relationship(
        back_populates="company", passive_deletes=True
    )
    invitations: Mapped[list[Invitation]] = relationship(
        back_populates="company", passive_deletes=True
    )

    __table_args__ = (
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="currency_iso4217_format"),
    )

    @validates("timezone")
    def _validate_timezone(self, _key: str, value: str | None) -> str | None:
        # The DB cannot check IANA names, so the model refuses bad ones early.
        if value is not None:
            try:
                ZoneInfo(value)
            except (ZoneInfoNotFoundError, ValueError) as exc:
                raise ValueError(f"unknown IANA timezone: {value!r}") from exc
        return value


class Team(IdMixin, TimestampMixin, Base):
    __tablename__ = "team"

    company_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("company.id", ondelete="CASCADE"), index=True
    )

    __table_args__ = (
        # Target for composite FKs from employee / work_order
        UniqueConstraint("id", "company_id", name="uq_team_id_company_id"),
    )

    company: Mapped[Company] = relationship(back_populates="teams")
    employees: Mapped[list[Employee]] = relationship(
        back_populates="team",
        foreign_keys="Employee.team_id",
        primaryjoin="Team.id == Employee.team_id",
    )
    work_orders: Mapped[list[WorkOrder]] = relationship(
        back_populates="team",
        foreign_keys="WorkOrder.team_id",
        primaryjoin="Team.id == WorkOrder.team_id",
    )


class EmployeePermission(enum.StrEnum):
    """What an employee may do inside the company. Code branches on THIS,
    never on the free-text `employee.role`."""

    OWNER = "owner"  # exactly one per company (enforced by a partial unique index)
    ADMIN = "admin"
    MEMBER = "member"


def _permission_enum() -> Enum:
    # native_enum=False -> VARCHAR. create_constraint=False because the CHECK is
    # declared explicitly in __table_args__ (True makes autogenerate emit it twice).
    return Enum(
        EmployeePermission,
        native_enum=False,
        length=20,
        create_constraint=False,
        name="employee_permission",
        values_callable=lambda e: [m.value for m in e],
    )


PERMISSION_CHECK = "permission IN ('owner', 'admin', 'member')"


class Employee(IdMixin, TimestampMixin, Base):
    __tablename__ = "employee"

    # One company per user (MVP decision): the UNIQUE below enforces it.
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE")
    )
    company_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("company.id", ondelete="CASCADE"), index=True
    )
    team_id: Mapped[int | None] = mapped_column(BigInteger)
    # Free text on purpose: roles depend on the services each company offers.
    # Promote to an enum/table once the real set of roles is known.
    role: Mapped[str | None] = mapped_column(String)
    permission: Mapped[EmployeePermission | None] = mapped_column(
        _permission_enum(), server_default=EmployeePermission.MEMBER.value
    )

    __table_args__ = (
        # One company per user. If many companies per user are allowed later,
        # replace with UNIQUE (user_id, company_id).
        UniqueConstraint("user_id", name="uq_employee_user_id"),
        UniqueConstraint("id", "company_id", name="uq_employee_id_company_id"),
        # Exactly one owner per company at most. ("At least one" is an
        # application rule: the owner cannot leave or be removed.)
        Index(
            "uq_employee_company_id_owner",
            "company_id",
            unique=True,
            postgresql_where=text("permission = 'owner'"),
        ),
        CheckConstraint(PERMISSION_CHECK, name="permission_valid"),
        # Team must belong to the same company as the employee.
        # Not checked while team_id is NULL (Postgres MATCH SIMPLE).
        ForeignKeyConstraint(
            ["team_id", "company_id"],
            ["team.id", "team.company_id"],
            name="fk_employee_team_same_company",
            ondelete="RESTRICT",
        ),
        Index("ix_employee_team_id", "team_id"),
    )

    user: Mapped[User] = relationship(back_populates="employments")
    company: Mapped[Company] = relationship(back_populates="employees")
    team: Mapped[Team | None] = relationship(
        back_populates="employees",
        foreign_keys=[team_id],
        primaryjoin="Team.id == Employee.team_id",
    )
    registry_entries: Mapped[list[EmployeeRegistry]] = relationship(
        back_populates="employee",
        foreign_keys="EmployeeRegistry.employee_id",
        primaryjoin="Employee.id == EmployeeRegistry.employee_id",
    )
    photos: Mapped[list[WorkOrderPhoto]] = relationship(
        back_populates="employee",
        foreign_keys="WorkOrderPhoto.employee_id",
        primaryjoin="Employee.id == WorkOrderPhoto.employee_id",
    )


class EmployeeRegistry(IdMixin, TimestampMixin, Base):
    """Clock-in/clock-out records. hour_end is NULL while the shift is open."""

    __tablename__ = "employee_registry"

    employee_id: Mapped[int] = mapped_column(BigInteger)
    company_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("company.id", ondelete="CASCADE"), index=True
    )
    hour_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    hour_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    extra_hours: Mapped[int | None] = mapped_column()

    __table_args__ = (
        ForeignKeyConstraint(
            ["employee_id", "company_id"],
            ["employee.id", "employee.company_id"],
            name="fk_employee_registry_employee_same_company",
            ondelete="CASCADE",
        ),
        Index("ix_employee_registry_employee_id", "employee_id"),
        CheckConstraint(
            "hour_end IS NULL OR hour_end > hour_start", name="hour_end_after_start"
        ),
        CheckConstraint("extra_hours >= 0", name="extra_hours_non_negative"),
    )

    employee: Mapped[Employee] = relationship(
        back_populates="registry_entries",
        foreign_keys=[employee_id],
        primaryjoin="Employee.id == EmployeeRegistry.employee_id",
    )


class Invitation(IdMixin, TimestampMixin, Base):
    """Invite an email address to join a company. The only way to become an
    employee of an existing company. Only the token's HASH is stored.

    Who may invite is an application rule (the company's owner, for now); the
    database records who did (`invited_by`) and keeps it in the same company.
    """

    __tablename__ = "invitation"

    company_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("company.id", ondelete="CASCADE"), index=True
    )
    invited_by: Mapped[int] = mapped_column(BigInteger)
    # Stored lowercased (CHECK below) so matching the accepting account is exact.
    email: Mapped[str | None] = mapped_column(String)
    permission: Mapped[EmployeePermission | None] = mapped_column(
        _permission_enum(), server_default=EmployeePermission.MEMBER.value
    )
    token_hash: Mapped[str] = mapped_column(String, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        ForeignKeyConstraint(
            ["invited_by", "company_id"],
            ["employee.id", "employee.company_id"],
            name="fk_invitation_inviter_same_company",
            ondelete="RESTRICT",
        ),
        Index("ix_invitation_invited_by", "invited_by"),
        # At most one PENDING invitation per email per company.
        Index(
            "uq_invitation_pending_company_id_email",
            "company_id",
            "email",
            unique=True,
            postgresql_where=text("accepted_at IS NULL"),
        ),
        CheckConstraint("email = lower(email)", name="email_lowercase"),
        CheckConstraint(PERMISSION_CHECK, name="permission_valid"),
        # There is a single owner (the founder); nobody can be invited as one.
        CheckConstraint("permission <> 'owner'", name="not_owner"),
    )

    company: Mapped[Company] = relationship(back_populates="invitations")
    inviter: Mapped[Employee] = relationship(
        foreign_keys=[invited_by],
        primaryjoin="Employee.id == Invitation.invited_by",
    )
