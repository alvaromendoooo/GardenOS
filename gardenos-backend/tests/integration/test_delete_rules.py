"""ON DELETE behaviour: what is protected (RESTRICT) and what goes away
together with its parent (CASCADE)."""

from sqlalchemy import text

from tests.integration.helpers import World, count, insert, violated_constraint

TENANT_TABLES = [
    "team", "customer", "property", "schedule", "service",
    "employee", "work_order", "work", "work_order_photo", "employee_registry",
]


def _add_work_and_photo(conn, t):
    insert(conn, "work", company_id=t.company, work_order_id=t.work_order, service_id=t.service)
    insert(conn, "work_order_photo", company_id=t.company, work_order_id=t.work_order, employee_id=t.employee)
    insert(conn, "employee_registry", company_id=t.company, employee_id=t.employee)


def test_deleting_a_company_removes_all_its_data_and_only_its_data(conn, world: World):
    _add_work_and_photo(conn, world.a)
    _add_work_and_photo(conn, world.b)

    conn.execute(text("DELETE FROM company WHERE id = :c"), {"c": world.a.company})

    for table in TENANT_TABLES:
        assert count(conn, table, company_id=world.a.company) == 0, table
        assert count(conn, table, company_id=world.b.company) > 0, f"{table} of B was lost"


def test_deleting_a_work_order_removes_its_works_and_photos(conn, world: World):
    _add_work_and_photo(conn, world.a)

    conn.execute(text("DELETE FROM work_order WHERE id = :w"), {"w": world.a.work_order})

    assert count(conn, "work", work_order_id=world.a.work_order) == 0
    assert count(conn, "work_order_photo", work_order_id=world.a.work_order) == 0


def test_deleting_a_customer_removes_its_properties(conn, world: World):
    # work orders of the property must go first (RESTRICT), see next test
    conn.execute(text("DELETE FROM work_order WHERE company_id = :c"), {"c": world.a.company})

    conn.execute(text("DELETE FROM customer WHERE id = :c"), {"c": world.a.customer})

    assert count(conn, "property", customer_id=world.a.customer) == 0


def test_property_with_work_orders_cannot_be_deleted(conn, world: World):
    violated = violated_constraint(
        conn, "DELETE FROM property WHERE id = :p", p=world.a.property
    )

    assert violated == "fk_work_order_property_same_company"


def test_team_with_employees_cannot_be_deleted(conn, world: World):
    conn.execute(text("DELETE FROM work_order WHERE company_id = :c"), {"c": world.a.company})

    violated = violated_constraint(conn, "DELETE FROM team WHERE id = :t", t=world.a.team)

    assert violated == "fk_employee_team_same_company"


def test_service_used_by_work_cannot_be_deleted(conn, world: World):
    _add_work_and_photo(conn, world.a)

    violated = violated_constraint(conn, "DELETE FROM service WHERE id = :s", s=world.a.service)

    assert violated == "fk_work_service_same_company"


def test_employee_with_photos_cannot_be_deleted(conn, world: World):
    _add_work_and_photo(conn, world.a)

    violated = violated_constraint(conn, "DELETE FROM employee WHERE id = :e", e=world.a.employee)

    assert violated == "fk_work_order_photo_employee_same_company"


def test_schedule_used_by_a_work_order_cannot_be_deleted(conn, world: World):
    violated = violated_constraint(
        conn, "DELETE FROM schedule WHERE id = :s", s=world.a.schedule
    )

    assert violated == "fk_work_order_schedule_same_company"


def test_deleting_a_user_removes_auth_and_employments(conn, world: World):
    insert(conn, "auth", user_id=world.a.user, email="gone@example.com")
    conn.execute(text("DELETE FROM work_order WHERE company_id = :c"), {"c": world.a.company})

    conn.execute(text("DELETE FROM users WHERE id = :u"), {"u": world.a.user})

    assert count(conn, "auth", user_id=world.a.user) == 0
    assert count(conn, "employee", user_id=world.a.user) == 0
