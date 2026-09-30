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

from datetime import datetime
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
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


class Employee(IdMixin, TimestampMixin, Base):
    __tablename__ = "employee"

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    company_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("company.id", ondelete="CASCADE"), index=True
    )
    team_id: Mapped[int | None] = mapped_column(BigInteger)
    # Free text on purpose: roles depend on the services each company offers.
    # Promote to an enum/table once the real set of roles is known.
    role: Mapped[str | None] = mapped_column(String)

    __table_args__ = (
        UniqueConstraint("user_id", "company_id", name="uq_employee_user_id_company_id"),
        UniqueConstraint("id", "company_id", name="uq_employee_id_company_id"),
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
