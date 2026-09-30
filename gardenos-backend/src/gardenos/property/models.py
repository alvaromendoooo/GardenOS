from __future__ import annotations

import enum
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    CheckConstraint
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from gardenos.shared.db import Base, IdMixin, TimestampMixin

if TYPE_CHECKING:
    from gardenos.customer.models import Customer
    from gardenos.workorder.models import WorkOrder


class PropertySize(enum.StrEnum):
    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"


class Property(IdMixin, TimestampMixin, Base):
    __tablename__ = "property"

    # company_id is denormalized (derivable via customer) on purpose: it lets the
    # DB enforce tenancy and lets queries filter by company without joins.
    company_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("company.id", ondelete="CASCADE"), index=True
    )
    customer_id: Mapped[int] = mapped_column(BigInteger)
    location: Mapped[str | None] = mapped_column(String)
    # native_enum=False -> VARCHAR + CHECK. Native PG enums are painful to alter
    # with Alembic (you cannot drop a value), so they are avoided here.
    size: Mapped[PropertySize | None] = mapped_column(
        Enum(
            PropertySize,
            native_enum=False,
            length=20,
            create_constraint=False,
            name="property_size",
            values_callable=lambda e: [m.value for m in e],
        )
    )

    __table_args__ = (
        UniqueConstraint("id", "company_id", name="uq_property_id_company_id"),
        ForeignKeyConstraint(
            ["customer_id", "company_id"],
            ["customer.id", "customer.company_id"],
            name="fk_property_customer_same_company",
            ondelete="CASCADE",
        ),
        Index("ix_property_customer_id", "customer_id"),
        CheckConstraint(
            "size IN ('small', 'medium', 'large')",
            name="ck_property_property_size"
        ),
    )

    customer: Mapped[Customer] = relationship(
        back_populates="properties",
        foreign_keys=[customer_id],
        primaryjoin="Customer.id == Property.customer_id",
    )
    work_orders: Mapped[list[WorkOrder]] = relationship(
        back_populates="property",
        foreign_keys="WorkOrder.property_id",
        primaryjoin="Property.id == WorkOrder.property_id",
    )
