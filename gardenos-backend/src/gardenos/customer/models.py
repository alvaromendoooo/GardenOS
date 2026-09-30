from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from gardenos.shared.db import Base, IdMixin, TimestampMixin

if TYPE_CHECKING:
    from gardenos.organization.models import Company
    from gardenos.property.models import Property


class Customer(IdMixin, TimestampMixin, Base):
    __tablename__ = "customer"

    company_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("company.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str | None] = mapped_column(String)
    email: Mapped[str | None] = mapped_column(String)
    phone: Mapped[str | None] = mapped_column(String)

    __table_args__ = (
        UniqueConstraint("id", "company_id", name="uq_customer_id_company_id"),
    )

    company: Mapped[Company] = relationship(back_populates="customers")
    properties: Mapped[list[Property]] = relationship(
        back_populates="customer",
        foreign_keys="Property.customer_id",
        primaryjoin="Customer.id == Property.customer_id",
        passive_deletes=True,
    )
