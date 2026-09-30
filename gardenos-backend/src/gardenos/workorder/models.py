from __future__ import annotations

import enum
from datetime import timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Interval,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from gardenos.shared.db import Base, IdMixin, TimestampMixin

if TYPE_CHECKING:
    from gardenos.organization.models import Company, Employee, Team
    from gardenos.property.models import Property
    from gardenos.scheduling.models import Schedule
    from gardenos.service.models import Service


class WorkOrderStatus(enum.StrEnum):
    PENDING = "pending"  # created, not yet scheduled/assigned
    SCHEDULED = "scheduled"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class WorkOrder(IdMixin, TimestampMixin, Base):
    __tablename__ = "work_order"

    company_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("company.id", ondelete="CASCADE"), index=True
    )
    property_id: Mapped[int] = mapped_column(BigInteger)
    team_id: Mapped[int | None] = mapped_column(BigInteger)
    schedule_id: Mapped[int | None] = mapped_column(BigInteger)
    status: Mapped[WorkOrderStatus | None] = mapped_column(
        Enum(
            WorkOrderStatus,
            native_enum=False,
            length=20,
            # The CHECK is declared once, explicitly, in __table_args__ below.
            # create_constraint=True makes Alembic autogenerate it twice.
            create_constraint=False,
            name="work_order_status",
            values_callable=lambda e: [m.value for m in e],
        ),
        server_default=WorkOrderStatus.PENDING.value,
    )

    __table_args__ = (
        UniqueConstraint("id", "company_id", name="uq_work_order_id_company_id"),
        ForeignKeyConstraint(
            ["property_id", "company_id"],
            ["property.id", "property.company_id"],
            name="fk_work_order_property_same_company",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["team_id", "company_id"],
            ["team.id", "team.company_id"],
            name="fk_work_order_team_same_company",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["schedule_id", "company_id"],
            ["schedule.id", "schedule.company_id"],
            name="fk_work_order_schedule_same_company",
            ondelete="RESTRICT",
        ),
        Index("ix_work_order_property_id", "property_id"),
        Index("ix_work_order_team_id", "team_id"),
        Index("ix_work_order_schedule_id", "schedule_id"),
        Index("ix_work_order_company_id_status", "company_id", "status"),
        CheckConstraint(
            "status IN ('pending', 'scheduled', 'in_progress', 'completed', 'cancelled')",
            name="status_valid",
        ),
    )

    company: Mapped[Company] = relationship(back_populates="work_orders")
    property: Mapped[Property] = relationship(
        back_populates="work_orders",
        foreign_keys=[property_id],
        primaryjoin="Property.id == WorkOrder.property_id",
    )
    team: Mapped[Team | None] = relationship(
        back_populates="work_orders",
        foreign_keys=[team_id],
        primaryjoin="Team.id == WorkOrder.team_id",
    )
    schedule: Mapped[Schedule | None] = relationship(
        back_populates="work_orders",
        foreign_keys=[schedule_id],
        primaryjoin="Schedule.id == WorkOrder.schedule_id",
    )
    works: Mapped[list[Work]] = relationship(
        back_populates="work_order",
        foreign_keys="Work.work_order_id",
        primaryjoin="WorkOrder.id == Work.work_order_id",
        passive_deletes=True,
    )
    photos: Mapped[list[WorkOrderPhoto]] = relationship(
        back_populates="work_order",
        foreign_keys="WorkOrderPhoto.work_order_id",
        primaryjoin="WorkOrder.id == WorkOrderPhoto.work_order_id",
        passive_deletes=True,
    )


class Work(IdMixin, TimestampMixin, Base):
    """One line of work inside a work order (a service performed)."""

    __tablename__ = "work"

    company_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("company.id", ondelete="CASCADE"), index=True
    )
    work_order_id: Mapped[int] = mapped_column(BigInteger)
    service_id: Mapped[int] = mapped_column(BigInteger)
    title: Mapped[str | None] = mapped_column(String)
    description: Mapped[str | None] = mapped_column(String)
    # NUMERIC, never float, for money. Currency comes from company.currency.
    payment: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    # A duration, not a clock time -> INTERVAL (timedelta)
    hours: Mapped[timedelta | None] = mapped_column(Interval)

    __table_args__ = (
        ForeignKeyConstraint(
            ["work_order_id", "company_id"],
            ["work_order.id", "work_order.company_id"],
            name="fk_work_work_order_same_company",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["service_id", "company_id"],
            ["service.id", "service.company_id"],
            name="fk_work_service_same_company",
            ondelete="RESTRICT",
        ),
        Index("ix_work_work_order_id", "work_order_id"),
        Index("ix_work_service_id", "service_id"),
        CheckConstraint("payment >= 0", name="payment_non_negative"),
    )

    work_order: Mapped[WorkOrder] = relationship(
        back_populates="works",
        foreign_keys=[work_order_id],
        primaryjoin="WorkOrder.id == Work.work_order_id",
    )
    service: Mapped[Service] = relationship(
        back_populates="works",
        foreign_keys=[service_id],
        primaryjoin="Service.id == Work.service_id",
    )


class WorkOrderPhoto(IdMixin, TimestampMixin, Base):
    """Photo taken by an employee while doing a work order.

    A separate table (not a column on work_order) because one order has many
    photos and we want to know who took each. `file_path` points to file storage.
    """

    __tablename__ = "work_order_photo"

    company_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("company.id", ondelete="CASCADE"), index=True
    )
    work_order_id: Mapped[int] = mapped_column(BigInteger)
    employee_id: Mapped[int] = mapped_column(BigInteger)
    file_path: Mapped[str | None] = mapped_column(String)

    __table_args__ = (
        ForeignKeyConstraint(
            ["work_order_id", "company_id"],
            ["work_order.id", "work_order.company_id"],
            name="fk_work_order_photo_work_order_same_company",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["employee_id", "company_id"],
            ["employee.id", "employee.company_id"],
            name="fk_work_order_photo_employee_same_company",
            ondelete="RESTRICT",
        ),
        Index("ix_work_order_photo_work_order_id", "work_order_id"),
        Index("ix_work_order_photo_employee_id", "employee_id"),
    )

    work_order: Mapped[WorkOrder] = relationship(
        back_populates="photos",
        foreign_keys=[work_order_id],
        primaryjoin="WorkOrder.id == WorkOrderPhoto.work_order_id",
    )
    employee: Mapped[Employee] = relationship(
        back_populates="photos",
        foreign_keys=[employee_id],
        primaryjoin="Employee.id == WorkOrderPhoto.employee_id",
    )
