"""Credentials, refresh tokens and one-time (verify/reset) tokens."""

import datetime as dt
import uuid

import pytest

from tests.integration.helpers import (
    World,
    count,
    insert,
    insert_violation,
    scalar,
)
from sqlalchemy import text

UTC = dt.timezone.utc
LATER = dt.datetime(2030, 1, 2, tzinfo=UTC)


def refresh_token(user_id: int, /, **overrides) -> dict:
    row = dict(
        user_id=user_id, token_hash="rt-1", family_id=uuid.uuid4(), expires_at=LATER
    )
    row.update(overrides)
    return row


def user_token(user_id: int, /, **overrides) -> dict:
    row = dict(
        user_id=user_id, purpose="email_verification", token_hash="ut-1", expires_at=LATER
    )
    row.update(overrides)
    return row


# ---- auth.email ------------------------------------------------------------


def test_auth_email_must_be_lowercase(conn, world: World):
    violated = insert_violation(conn, "auth", user_id=world.a.user, email="Ana@Example.com")

    assert violated == "ck_auth_email_lowercase"


def test_lowercase_email_makes_uniqueness_case_insensitive(conn, world: World):
    insert(conn, "auth", user_id=world.a.user, email="ana@example.com")

    # the only way to sneak in a "different case" duplicate is blocked by the CHECK
    violated = insert_violation(conn, "auth", user_id=world.b.user, email="ANA@example.com")

    assert violated == "ck_auth_email_lowercase"


# ---- refresh_token ---------------------------------------------------------


def test_refresh_token_can_be_stored(conn, world: World):
    token_id = insert(conn, "refresh_token", **refresh_token(world.a.user))

    row = conn.execute(
        text("SELECT revoked_at, created_at FROM refresh_token WHERE id = :i"), {"i": token_id}
    ).one()

    assert row.revoked_at is None
    assert row.created_at is not None


def test_refresh_token_hash_is_unique(conn, world: World):
    insert(conn, "refresh_token", **refresh_token(world.a.user))

    violated = insert_violation(conn, "refresh_token", **refresh_token(world.b.user))

    assert violated == "uq_refresh_token_token_hash"


@pytest.mark.parametrize("column", ["user_id", "token_hash", "family_id", "expires_at"])
def test_refresh_token_required_columns(conn, world: World, column):
    violated = insert_violation(
        conn, "refresh_token", **refresh_token(world.a.user, **{column: None})
    )

    assert violated == f"not_null:{column}"


def test_refresh_token_needs_an_existing_user(conn, world: World):
    violated = insert_violation(conn, "refresh_token", **refresh_token(999_999_999))

    assert violated == "fk_refresh_token_user_id_users"


def test_one_user_can_have_many_tokens_in_the_same_family(conn, world: World):
    """Rotation: the old (revoked) row and the new row share a family."""
    family = uuid.uuid4()
    insert(
        conn, "refresh_token",
        **refresh_token(world.a.user, token_hash="old", family_id=family,
                        revoked_at=dt.datetime(2030, 1, 1, tzinfo=UTC)),
    )
    insert(conn, "refresh_token", **refresh_token(world.a.user, token_hash="new", family_id=family))

    assert count(conn, "refresh_token", family_id=family) == 2


def test_deleting_a_user_deletes_their_tokens(conn, world: World):
    insert(conn, "refresh_token", **refresh_token(world.a.user))
    insert(conn, "user_token", **user_token(world.a.user))
    conn.execute(text("DELETE FROM work_order WHERE company_id = :c"), {"c": world.a.company})

    conn.execute(text("DELETE FROM users WHERE id = :u"), {"u": world.a.user})

    assert count(conn, "refresh_token", user_id=world.a.user) == 0
    assert count(conn, "user_token", user_id=world.a.user) == 0


# ---- user_token (email verification / password reset) ---------------------


@pytest.mark.parametrize("purpose", ["email_verification", "password_reset"])
def test_user_token_accepts_known_purposes(conn, world: World, purpose):
    insert(conn, "user_token", **user_token(world.a.user, purpose=purpose))


def test_user_token_rejects_unknown_purpose(conn, world: World):
    violated = insert_violation(conn, "user_token", **user_token(world.a.user, purpose="login"))

    assert violated == "ck_user_token_purpose_valid"


def test_user_token_hash_is_unique(conn, world: World):
    insert(conn, "user_token", **user_token(world.a.user))

    violated = insert_violation(conn, "user_token", **user_token(world.b.user))

    assert violated == "uq_user_token_token_hash"


@pytest.mark.parametrize("column", ["user_id", "purpose", "token_hash", "expires_at"])
def test_user_token_required_columns(conn, world: World, column):
    violated = insert_violation(
        conn, "user_token", **user_token(world.a.user, **{column: None})
    )

    assert violated == f"not_null:{column}"


def test_user_token_starts_unused(conn, world: World):
    token_id = insert(conn, "user_token", **user_token(world.a.user))

    used_at = scalar(conn, "SELECT used_at FROM user_token WHERE id = :i", i=token_id)

    assert used_at is None
