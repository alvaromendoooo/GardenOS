"""Permission levels, the single-owner rule and invitations."""

import datetime as dt

import pytest
from sqlalchemy import text

from tests.integration.helpers import (
    World,
    count,
    insert,
    insert_violation,
    scalar,
    violated_constraint,
)

UTC = dt.timezone.utc
TOMORROW = dt.datetime(2030, 1, 2, tzinfo=UTC)


def invitation(tenant, **overrides) -> dict:
    """A valid invitation row issued by `tenant`'s owner; override to break it."""
    row = dict(
        company_id=tenant.company,
        invited_by=tenant.employee,
        email="ana@example.com",
        permission="member",
        token_hash="hash-1",
        expires_at=TOMORROW,
    )
    row.update(overrides)
    return row


# ---- employee.permission ---------------------------------------------------


def test_employee_permission_defaults_to_member(conn, world: World):
    employee = insert(conn, "employee", user_id=world.free_user, company_id=world.a.company)

    permission = scalar(conn, "SELECT permission FROM employee WHERE id = :i", i=employee)

    assert permission == "member"


def test_unknown_permission_is_rejected(conn, world: World):
    violated = insert_violation(
        conn, "employee", user_id=world.free_user, company_id=world.a.company,
        permission="superuser",
    )

    assert violated == "ck_employee_permission_valid"


def test_a_company_cannot_have_two_owners(conn, world: World):
    violated = insert_violation(
        conn, "employee", user_id=world.free_user, company_id=world.a.company,
        permission="owner",
    )

    assert violated == "uq_employee_company_id_owner"


def test_each_company_has_its_own_owner(conn, world: World):
    # seed already created one owner in A and one in B
    assert count(conn, "employee", permission="owner") == 2


def test_company_can_have_many_admins_and_members(conn, world: World):
    other_users = [insert(conn, "users", username=f"staff-{i}") for i in range(3)]

    insert(conn, "employee", user_id=other_users[0], company_id=world.a.company, permission="admin")
    insert(conn, "employee", user_id=other_users[1], company_id=world.a.company, permission="admin")
    insert(conn, "employee", user_id=other_users[2], company_id=world.a.company, permission="member")


# ---- invitation ------------------------------------------------------------


def test_owner_can_invite_a_member_or_admin(conn, world: World):
    insert(conn, "invitation", **invitation(world.a, email="m@example.com", token_hash="h-m"))
    insert(
        conn, "invitation",
        **invitation(world.a, email="a@example.com", token_hash="h-a", permission="admin"),
    )


def test_nobody_can_be_invited_as_owner(conn, world: World):
    violated = insert_violation(conn, "invitation", **invitation(world.a, permission="owner"))

    assert violated == "ck_invitation_not_owner"


def test_invitation_defaults(conn, world: World):
    row = invitation(world.a)
    del row["permission"]
    invitation_id = insert(conn, "invitation", **row)

    result = conn.execute(
        text("SELECT permission, accepted_at, created_at FROM invitation WHERE id = :i"),
        {"i": invitation_id},
    ).one()

    assert result.permission == "member"
    assert result.accepted_at is None
    assert result.created_at is not None


def test_invitation_email_must_be_lowercase(conn, world: World):
    violated = insert_violation(conn, "invitation", **invitation(world.a, email="Ana@Example.com"))

    assert violated == "ck_invitation_email_lowercase"


def test_inviter_must_belong_to_the_same_company(conn, world: World):
    violated = insert_violation(
        conn, "invitation", **invitation(world.a, invited_by=world.b.employee)
    )

    assert violated == "fk_invitation_inviter_same_company"


def test_token_hash_is_unique(conn, world: World):
    insert(conn, "invitation", **invitation(world.a, email="one@example.com"))

    violated = insert_violation(
        conn, "invitation", **invitation(world.b, email="two@example.com")
    )

    assert violated == "uq_invitation_token_hash"


@pytest.mark.parametrize("column", ["token_hash", "expires_at", "invited_by", "company_id"])
def test_invitation_required_columns(conn, world: World, column):
    violated = insert_violation(conn, "invitation", **invitation(world.a, **{column: None}))

    assert violated == f"not_null:{column}"


def test_only_one_pending_invitation_per_email_and_company(conn, world: World):
    insert(conn, "invitation", **invitation(world.a))

    violated = insert_violation(conn, "invitation", **invitation(world.a, token_hash="hash-2"))

    assert violated == "uq_invitation_pending_company_id_email"


def test_can_reinvite_an_email_after_the_invitation_was_accepted(conn, world: World):
    insert(conn, "invitation", **invitation(world.a, accepted_at=dt.datetime(2030, 1, 1, tzinfo=UTC)))

    insert(conn, "invitation", **invitation(world.a, token_hash="hash-2"))


def test_same_email_can_be_pending_in_two_companies(conn, world: World):
    insert(conn, "invitation", **invitation(world.a))

    insert(conn, "invitation", **invitation(world.b, token_hash="hash-2"))


def test_deleting_a_company_also_deletes_its_invitations(conn, world: World):
    insert(conn, "invitation", **invitation(world.a))
    insert(conn, "invitation", **invitation(world.b, token_hash="hash-2"))

    conn.execute(text("DELETE FROM company WHERE id = :c"), {"c": world.a.company})

    assert count(conn, "invitation", company_id=world.a.company) == 0
    assert count(conn, "invitation", company_id=world.b.company) == 1


def test_inviter_cannot_be_deleted_while_invitations_exist(conn, world: World):
    insert(conn, "invitation", **invitation(world.a))
    conn.execute(text("DELETE FROM work_order WHERE company_id = :c"), {"c": world.a.company})

    violated = violated_constraint(
        conn, "DELETE FROM employee WHERE id = :e", e=world.a.employee
    )

    assert violated == "fk_invitation_inviter_same_company"
