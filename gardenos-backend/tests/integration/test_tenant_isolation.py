"""Tenant isolation enforced by the database itself.

Every tenant-owned table carries company_id and links to other tenant-owned
tables through composite FKs (x_id, company_id). These tests prove that a row
of company A can never reference data of company B, even with buggy app code.

NOTE: this guards WRITES only. Reads are not protected by the database:
handlers must still filter every query by the authenticated user's company_id.
"""

import pytest

from tests.integration.helpers import (
    World,
    insert,
    insert_violation,
    scalar,
    violated_constraint,
)

# name -> (table, columns(a, b, world), expected violated constraint)
CROSS_TENANT_INSERTS = {
    "work_order -> team of other company": (
        "work_order",
        lambda a, b, w: dict(company_id=a.company, property_id=a.property, team_id=b.team),
        "fk_work_order_team_same_company",
    ),
    "work_order -> property of other company": (
        "work_order",
        lambda a, b, w: dict(company_id=a.company, property_id=b.property),
        "fk_work_order_property_same_company",
    ),
    "work_order -> schedule of other company": (
        "work_order",
        lambda a, b, w: dict(company_id=a.company, property_id=a.property, schedule_id=b.schedule),
        "fk_work_order_schedule_same_company",
    ),
    "property -> customer of other company": (
        "property",
        lambda a, b, w: dict(company_id=a.company, customer_id=b.customer),
        "fk_property_customer_same_company",
    ),
    "employee -> team of other company": (
        "employee",
        lambda a, b, w: dict(user_id=w.free_user, company_id=a.company, team_id=b.team),
        "fk_employee_team_same_company",
    ),
    "work -> work_order of other company": (
        "work",
        lambda a, b, w: dict(company_id=a.company, work_order_id=b.work_order, service_id=a.service),
        "fk_work_work_order_same_company",
    ),
    "work -> service of other company": (
        "work",
        lambda a, b, w: dict(company_id=a.company, work_order_id=a.work_order, service_id=b.service),
        "fk_work_service_same_company",
    ),
    "work_order_photo -> work_order of other company": (
        "work_order_photo",
        lambda a, b, w: dict(company_id=a.company, work_order_id=b.work_order, employee_id=a.employee),
        "fk_work_order_photo_work_order_same_company",
    ),
    "work_order_photo -> employee of other company": (
        "work_order_photo",
        lambda a, b, w: dict(company_id=a.company, work_order_id=a.work_order, employee_id=b.employee),
        "fk_work_order_photo_employee_same_company",
    ),
    "employee_registry -> employee of other company": (
        "employee_registry",
        lambda a, b, w: dict(company_id=a.company, employee_id=b.employee),
        "fk_employee_registry_employee_same_company",
    ),
}


@pytest.mark.parametrize(
    ("table", "build", "constraint"),
    CROSS_TENANT_INSERTS.values(),
    ids=CROSS_TENANT_INSERTS.keys(),
)
def test_cross_tenant_reference_is_rejected(conn, world: World, table, build, constraint):
    columns = build(world.a, world.b, world)

    assert insert_violation(conn, table, **columns) == constraint


# Each "control" is the same insert as above but inside ONE company. If these
# were rejected too, the tests above would pass for the wrong reason.
SAME_TENANT_INSERTS = {
    "work_order with own team, property and schedule": (
        "work_order",
        lambda a, w: dict(
            company_id=a.company, property_id=a.property,
            team_id=a.team, schedule_id=a.schedule,
        ),
    ),
    "work_order without team or schedule": (
        "work_order",
        lambda a, w: dict(company_id=a.company, property_id=a.property),
    ),
    "property for own customer": (
        "property",
        lambda a, w: dict(company_id=a.company, customer_id=a.customer),
    ),
    "employee in own team": (
        "employee",
        lambda a, w: dict(user_id=w.free_user, company_id=a.company, team_id=a.team),
    ),
    "employee without team": (
        "employee",
        lambda a, w: dict(user_id=w.free_user, company_id=a.company),
    ),
    "work on own order with own service": (
        "work",
        lambda a, w: dict(company_id=a.company, work_order_id=a.work_order, service_id=a.service),
    ),
    "photo by own employee on own order": (
        "work_order_photo",
        lambda a, w: dict(company_id=a.company, work_order_id=a.work_order, employee_id=a.employee),
    ),
    "registry entry for own employee": (
        "employee_registry",
        lambda a, w: dict(company_id=a.company, employee_id=a.employee),
    ),
}


@pytest.mark.parametrize(
    ("table", "build"),
    SAME_TENANT_INSERTS.values(),
    ids=SAME_TENANT_INSERTS.keys(),
)
def test_same_tenant_reference_is_accepted(conn, world: World, table, build):
    columns = build(world.a, world)

    new_id = insert(conn, table, **columns)

    assert new_id is not None


def test_user_cannot_be_employee_of_two_companies(conn, world: World):
    """MVP rule: one company per user."""
    insert(conn, "employee", user_id=world.free_user, company_id=world.a.company)

    violated = insert_violation(
        conn, "employee", user_id=world.free_user, company_id=world.b.company
    )

    assert violated == "uq_employee_user_id"


def test_same_service_name_is_allowed_in_different_companies(conn, world: World):
    insert(conn, "service", company_id=world.a.company, name="Mowing")
    insert(conn, "service", company_id=world.b.company, name="Mowing")


def test_company_id_cannot_be_changed_to_orphan_children(conn, world: World):
    """Moving a team to another company would orphan its employees' tenancy."""
    constraint = violated_constraint(
        conn,
        "UPDATE team SET company_id = :b WHERE id = :t",
        b=world.b.company, t=world.a.team,
    )

    assert constraint is not None

