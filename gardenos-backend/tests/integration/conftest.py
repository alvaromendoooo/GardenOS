import pytest
from sqlalchemy import Connection

from tests.integration.helpers import World, insert, seed_tenant


@pytest.fixture
def world(conn: Connection) -> World:
    """Two fully independent companies, A (Spain) and B (US), each with a team,
    customer, property, schedule, service, employee and work order."""
    a = seed_tenant(conn, "A", "EUR", "Europe/Madrid")
    b = seed_tenant(conn, "B", "USD", "America/New_York")
    free_user = insert(conn, "users", username="free-user")
    return World(a=a, b=b, free_user=free_user)
