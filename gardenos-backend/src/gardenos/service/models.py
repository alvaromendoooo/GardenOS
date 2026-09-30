from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from gardenos.shared.db import Base, IdMixin, TimestampMixin

if TYPE_CHECKING:
    from gardenos.organization.models import Company
    from gardenos.workorder.models import Work


class Service(IdMixin, TimestampMixin, Base):
    """A company's service catalog entry (e.g. "Lawn mowing"). Tenant-owned."""

    __tablename__ = "service"

    company_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("company.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str | None] = mapped_column(String)
    description: Mapped[str | None] = mapped_column(String)

    __table_args__ = (
        UniqueConstraint("id", "company_id", name="uq_service_id_company_id"),
        # No two services with the same name inside one company
        UniqueConstraint("company_id", "name", name="uq_service_company_id_name"),
    )

    company: Mapped[Company] = relationship(back_populates="services")
    works: Mapped[list[Work]] = relationship(
        back_populates="service",
        foreign_keys="Work.service_id",
        primaryjoin="Service.id == Work.service_id",
    )
