"""Integration-test fixtures.

A single throwaway PostgreSQL container is started per test session and the
REAL Alembic migrations are applied to it (not Base.metadata.create_all), so
these tests verify the schema exactly as production will get it.

Safety: DATABASE_URL is overridden *before* `config.config` is first imported.
pydantic-settings gives environment variables priority over .env, so nothing
in these tests can touch the development database.
"""

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, Engine, create_engine
from testcontainers.community.postgres import PostgresContainer

BACKEND_ROOT = Path(__file__).resolve().parent.parent

# Same major version as compose.yml (unpinned "postgres" image there).
POSTGRES_IMAGE = "postgres:latest"


def alembic_config() -> Config:
    return Config(str(BACKEND_ROOT / "alembic.ini"))


@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    with PostgresContainer(POSTGRES_IMAGE, driver="psycopg") as pg:
        url = pg.get_connection_url()
        os.environ["DATABASE_URL"] = url
        # Required by Settings; a throwaway value so tests never need the real one.
        os.environ.setdefault("SECRET_KEY", "test-only-secret-key")

        # Guard: if `config` was imported earlier, the singleton is stale and
        # Alembic would migrate the wrong database. Fail loudly instead.
        from config.config import settings

        assert str(settings.DATABASE_URL) == url, (
            "settings.DATABASE_URL does not point at the test container; "
            "something imported config.config before the tests set DATABASE_URL"
        )

        command.upgrade(alembic_config(), "head")

        eng = create_engine(url)
        try:
            yield eng
        finally:
            eng.dispose()


@pytest.fixture
def conn(engine: Engine) -> Iterator[Connection]:
    """A connection inside a transaction that is always rolled back,
    so every test starts from an empty database and leaves nothing behind."""
    with engine.connect() as connection:
        outer = connection.begin()
        try:
            yield connection
        finally:
            outer.rollback()
