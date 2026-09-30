"""The migrations themselves: they must match the models and be reversible."""

from alembic import command
from sqlalchemy import Engine, inspect

from tests.conftest import alembic_config

EXPECTED_TABLES = {
    "users", "auth", "company", "customer", "property", "team", "employee",
    "employee_registry", "service", "schedule", "work_order", "work", "work_order_photo",
    "invitation", "refresh_token", "user_token",
}


def test_models_and_migrations_have_no_drift(engine: Engine):
    """Fails if a model was changed without generating a migration
    (equivalent to `alembic check`)."""
    command.check(alembic_config())


def test_upgrade_creates_every_table(engine: Engine):
    tables = set(inspect(engine).get_table_names())

    assert EXPECTED_TABLES <= tables


def test_every_foreign_key_column_is_indexed(engine: Engine):
    """Postgres does not index FK columns automatically; unindexed FKs make
    joins and cascading deletes slow."""
    insp = inspect(engine)
    unindexed = []
    for table in EXPECTED_TABLES:
        indexed_leading = {ix["column_names"][0] for ix in insp.get_indexes(table)}
        indexed_leading |= {
            uq["column_names"][0] for uq in insp.get_unique_constraints(table)
        }
        for fk in insp.get_foreign_keys(table):
            if fk["constrained_columns"][0] not in indexed_leading:
                unindexed.append((table, fk["name"]))

    assert not unindexed


def test_downgrade_then_upgrade_round_trip(engine: Engine):
    """Every migration must be reversible. Always leaves the DB at head."""
    cfg = alembic_config()
    try:
        command.downgrade(cfg, "base")
        remaining = EXPECTED_TABLES & set(inspect(engine).get_table_names())
        assert not remaining
    finally:
        command.upgrade(cfg, "head")

    assert EXPECTED_TABLES <= set(inspect(engine).get_table_names())
