"""Imports every model so they register on Base.metadata.

Alembic's env.py imports this module; a model that is not imported here is
invisible to autogenerate.
"""

from gardenos.auth.models import Auth, User
from gardenos.customer.models import Customer
from gardenos.organization.models import Company, Employee, EmployeeRegistry, Team
from gardenos.property.models import Property
from gardenos.scheduling.models import Schedule
from gardenos.service.models import Service
from gardenos.shared.db import Base
from gardenos.workorder.models import Work, WorkOrder, WorkOrderPhoto

__all__ = [
    "Auth", "Base", "Company", "Customer", "Employee", "EmployeeRegistry",
    "Property", "Schedule", "Service", "Team", "User", "Work", "WorkOrder",
    "WorkOrderPhoto",
]
