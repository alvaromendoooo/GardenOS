"""Column-level rules: CHECKs, UNIQUEs, defaults. (Tenant rules live in
test_tenant_isolation.py, delete rules in test_delete_rules.py.)"""

import datetime as dt

import pytest
from sqlalchemy import text

from tests.integration.helpers import World, insert, insert_violation, scalar

UTC = dt.timezone.utc

# name -> (table, columns(a, world), substring expected in violated constraint name)
INVALID_ROWS = {
    "work_order status outside the allowed set": (
        "work_order",
        lambda a, w: dict(company_id=a.company, property_id=a.property, status="bogus"),
        "status_valid",
    ),
    "property size outside the allowed set": (
        "property",
        lambda a, w: dict(company_id=a.company, customer_id=a.customer, size="huge"),
        "size",
    ),
    "negative work payment": (
        "work",
        lambda a, w: dict(
            company_id=a.company, work_order_id=a.work_order,
            service_id=a.service, payment=-1,
        ),
        "payment_non_negative",
    ),
    "schedule ending before it starts": (
        "schedule",
        lambda a, w: dict(
            company_id=a.company, date=dt.date(2026, 10, 1),
            start_time=dt.time(10), end_time=dt.time(9),
        ),
        "end_after_start",
    ),
    "schedule with zero length": (
        "schedule",
        lambda a, w: dict(
            company_id=a.company, date=dt.date(2026, 10, 1),
            start_time=dt.time(9), end_time=dt.time(9),
        ),
        "end_after_start",
    ),
    "lowercase currency code": (
        "company",
        lambda a, w: dict(name="X", currency="eur"),
        "currency_iso4217_format",
    ),
    "currency code with wrong length": (
        "company",
        lambda a, w: dict(name="X", currency="EU"),
        "currency_iso4217_format",
    ),
    "clock-out before clock-in": (
        "employee_registry",
        lambda a, w: dict(
            company_id=a.company, employee_id=a.employee,
            hour_start=dt.datetime(2026, 10, 1, 10, tzinfo=UTC),
            hour_end=dt.datetime(2026, 10, 1, 9, tzinfo=UTC),
        ),
        "hour_end_after_start",
    ),
    "negative extra hours": (
        "employee_registry",
        lambda a, w: dict(company_id=a.company, employee_id=a.employee, extra_hours=-1),
        "extra_hours_non_negative",
    ),
    "duplicate service name inside one company": (
        "service",
        lambda a, w: dict(company_id=a.company, name="service A"),
        "uq_service_company_id_name",
    ),
    "user employed twice by the same company": (
        "employee",
        lambda a, w: dict(user_id=a.user, company_id=a.company),
        "uq_employee_user_id",
    ),
    "user employed by a second company": (
        "employee",
        lambda a, w: dict(user_id=a.user, company_id=w.b.company),
        "uq_employee_user_id",
    ),
    "duplicate username": (
        "users",
        lambda a, w: dict(username="user-A"),
        "uq_users_username",
    ),
}


@pytest.mark.parametrize(
    ("table", "build", "expected"),
    INVALID_ROWS.values(),
    ids=INVALID_ROWS.keys(),
)
def test_invalid_row_is_rejected(conn, world: World, table, build, expected):
    violated = insert_violation(conn, table, **build(world.a, world))

    assert violated is not None, "the database accepted an invalid row"
    assert expected in violated


def test_auth_email_must_be_unique(conn, world: World):
    insert(conn, "auth", user_id=world.a.user, email="same@example.com")

    violated = insert_violation(conn, "auth", user_id=world.free_user, email="same@example.com")

    assert violated == "uq_auth_email"


def test_user_has_at_most_one_auth_row(conn, world: World):
    insert(conn, "auth", user_id=world.a.user, email="one@example.com")

    violated = insert_violation(conn, "auth", user_id=world.a.user, email="two@example.com")

    assert violated == "uq_auth_user_id"


def test_open_shift_is_allowed(conn, world: World):
    """hour_end is NULL while the employee is still clocked in."""
    insert(
        conn, "employee_registry", company_id=world.a.company, employee_id=world.a.employee,
        hour_start=dt.datetime(2026, 10, 1, 8, tzinfo=UTC),
    )


# ---- defaults -------------------------------------------------------------


def test_work_order_status_defaults_to_pending(conn, world: World):
    order = insert(conn, "work_order", company_id=world.a.company, property_id=world.a.property)

    status = scalar(conn, "SELECT status FROM work_order WHERE id = :i", i=order)

    assert status == "pending"


def test_public_id_and_timestamps_are_generated(conn, world: World):
    row = conn.execute(
        text("SELECT public_id, created_at, updated_at FROM company WHERE id = :i"),
        {"i": world.a.company},
    ).one()

    assert all(value is not None for value in row)


def test_auth_flags_have_safe_defaults(conn, world: World):
    auth = insert(conn, "auth", user_id=world.a.user, email="d@example.com")

    row = conn.execute(
        text("SELECT is_active, is_verified FROM auth WHERE id = :i"), {"i": auth}
    ).one()

    assert (row.is_active, row.is_verified) == (True, False)


def test_public_ids_are_unique_per_row(conn, world: World):
    ids = conn.execute(text("SELECT public_id FROM company")).scalars().all()

    assert len(ids) == len(set(ids)) == 2


def test_payment_keeps_exact_decimal_value(conn, world: World):
    """Money is NUMERIC, so 0.10 + 0.20 is exactly 0.30 (floats would give 0.30000000000000004)."""
    a = world.a
    for amount in ("0.10", "0.20"):
        insert(
            conn, "work", company_id=a.company, work_order_id=a.work_order,
            service_id=a.service, payment=amount,
        )

    total = scalar(conn, "SELECT sum(payment) FROM work WHERE work_order_id = :w", w=a.work_order)

    assert str(total) == "0.30"
