"""Small SQL helpers for the integration tests.

Tests talk to the database with plain SQL on purpose: they verify what the
*database* enforces, independent of any ORM behaviour.
"""

from dataclasses import dataclass

from sqlalchemy import Connection, text
from sqlalchemy.exc import IntegrityError


def insert(conn: Connection, table: str, **columns) -> int:
    """INSERT one row and return its id. Table/column names come from test code only."""
    cols = ", ".join(columns)
    params = ", ".join(f":{c}" for c in columns)
    sql = f"INSERT INTO {table} ({cols}) VALUES ({params}) RETURNING id"
    return conn.execute(text(sql), columns).scalar_one()


def insert_default_row(conn: Connection, table: str) -> int:
    return conn.execute(text(f"INSERT INTO {table} DEFAULT VALUES RETURNING id")).scalar_one()


def scalar(conn: Connection, sql: str, **params):
    return conn.execute(text(sql), params).scalar_one()


def count(conn: Connection, table: str, **where) -> int:
    clause = " AND ".join(f"{c} = :{c}" for c in where) or "TRUE"
    return scalar(conn, f"SELECT count(*) FROM {table} WHERE {clause}", **where)


def violated_constraint(conn: Connection, sql: str, **params) -> str | None:
    """Run a statement that must fail; return the name of the violated constraint.

    Runs in a SAVEPOINT so the surrounding test transaction stays usable.
    Returns None if the statement was (wrongly) accepted. NOT NULL violations
    have no constraint name, so they are reported as "not_null:<column>".
    """
    savepoint = conn.begin_nested()
    try:
        conn.execute(text(sql), params)
    except IntegrityError as exc:
        savepoint.rollback()
        diag = exc.orig.diag
        return diag.constraint_name or f"not_null:{diag.column_name}"
    savepoint.rollback()
    return None


def insert_violation(conn: Connection, table: str, **columns) -> str | None:
    cols = ", ".join(columns)
    params = ", ".join(f":{c}" for c in columns)
    return violated_constraint(conn, f"INSERT INTO {table} ({cols}) VALUES ({params})", **columns)


@dataclass
class Tenant:
    """All the ids of one company's seeded data."""

    company: int
    team: int
    customer: int
    property: int
    schedule: int
    service: int
    user: int
    employee: int
    work_order: int


@dataclass
class World:
    a: Tenant
    b: Tenant
    free_user: int  # a user who is not an employee anywhere


def seed_tenant(conn: Connection, name: str, currency: str, tz: str) -> Tenant:
    import datetime as dt

    company = insert(conn, "company", name=name, currency=currency, timezone=tz)
    team = insert(conn, "team", company_id=company)
    customer = insert(conn, "customer", company_id=company, name=f"customer {name}")
    prop = insert(conn, "property", company_id=company, customer_id=customer, size="small")
    schedule = insert(
        conn, "schedule", company_id=company,
        date=dt.date(2026, 10, 1), start_time=dt.time(9), end_time=dt.time(10),
    )
    service = insert(conn, "service", company_id=company, name=f"service {name}")
    user = insert(conn, "users", username=f"user-{name}")
    employee = insert(
        conn, "employee", user_id=user, company_id=company,
        team_id=team, role="mower", permission="owner",
    )
    work_order = insert(
        conn, "work_order", company_id=company,
        property_id=prop, team_id=team, schedule_id=schedule,
    )
    return Tenant(company, team, customer, prop, schedule, service, user, employee, work_order)
