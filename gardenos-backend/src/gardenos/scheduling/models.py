from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from sqlalchemy import BigInteger, CheckConstraint, Date, ForeignKey, Time, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from gardenos.shared.db import Base, IdMixin, TimestampMixin

if TYPE_CHECKING:
    from gardenos.organization.models import Company
    from gardenos.workorder.models import WorkOrder


class Schedule(IdMixin, TimestampMixin, Base):
    """date + start/end are wall-clock values in the owning company's timezone.

    The timezone is NOT stored here: company.timezone is the single source of
    truth, so changing it is one UPDATE and a schedule can never disagree with
    its company. Use `starts_at` / `ends_at` to get real (aware) datetimes.
    """

    __tablename__ = "schedule"

    company_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("company.id", ondelete="CASCADE"), index=True
    )
    date: Mapped[dt.date | None] = mapped_column(Date)
    start_time: Mapped[dt.time | None] = mapped_column(Time)
    end_time: Mapped[dt.time | None] = mapped_column(Time)

    __table_args__ = (
        UniqueConstraint("id", "company_id", name="uq_schedule_id_company_id"),
        CheckConstraint("end_time > start_time", name="end_after_start"),
    )

    company: Mapped[Company] = relationship()
    # Several work orders may share one slot (e.g. a team's morning route).
    work_orders: Mapped[list[WorkOrder]] = relationship(
        back_populates="schedule",
        foreign_keys="WorkOrder.schedule_id",
        primaryjoin="Schedule.id == WorkOrder.schedule_id",
    )

    @property
    def tzinfo(self) -> ZoneInfo | None:
        tz = self.company.timezone
        return ZoneInfo(tz) if tz else None

    @property
    def starts_at(self) -> dt.datetime | None:
        return self._localize(self.start_time)

    @property
    def ends_at(self) -> dt.datetime | None:
        return self._localize(self.end_time)

    def _localize(self, t: dt.time | None) -> dt.datetime | None:
        tz = self.tzinfo
        if self.date is None or t is None or tz is None:
            return None
        return dt.datetime.combine(self.date, t, tzinfo=tz)
