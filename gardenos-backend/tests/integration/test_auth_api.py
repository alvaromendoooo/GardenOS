"""Auth flows end to end: HTTP -> controller -> service -> real PostgreSQL.

These are API tests: they use Flask's test client and assert on responses AND on
what ended up in the database (e.g. only hashes are stored, tokens get revoked).
The service commits for real, so every test truncates the tables afterwards.
"""

import pytest
from sqlalchemy import text

EMAIL = "ana@example.com"
PASSWORD = "correct-horse-1"


# ---- fixtures ---------------------------------------------------------------


@pytest.fixture(scope="session")
def app(engine):
    # `engine` first: it points DATABASE_URL at the container and migrates it,
    # and config.config must not be imported before that happens.
    from gardenos import create_app
    from gardenos.auth import service

    # bcrypt cost 12 (~0.25 s per hash) would make this suite slow for no benefit
    service.bcrypt._log_rounds = 4

    app = create_app()
    app.config.update(TESTING=True)
    return app


@pytest.fixture(autouse=True)
def limiter_off(app):
    """Rate limits are off by default; the tests that need them switch them on."""
    from gardenos.shared.limiter import limiter

    limiter.enabled = False
    limiter.reset()
    yield limiter
    limiter.enabled = False
    limiter.reset()


@pytest.fixture
def db(engine):
    """Run SQL in its own committed transaction; returns the rows (if any)."""

    def run(sql: str, **params):
        with engine.begin() as c:
            result = c.execute(text(sql), params)
            return result.all() if result.returns_rows else None

    return run


@pytest.fixture
def client(app, db):
    yield app.test_client()
    db("TRUNCATE users, company RESTART IDENTITY CASCADE")


class Mailbox:
    """Stands in for email: collects the raw tokens the app 'sends'."""

    def __init__(self):
        self.sent: list[tuple[str, str, str]] = []

    def tokens(self, kind: str) -> list[str]:
        return [token for k, _, token in self.sent if k == kind]

    def last(self, kind: str) -> str:
        return self.tokens(kind)[-1]


@pytest.fixture
def mailbox(monkeypatch):
    box = Mailbox()
    monkeypatch.setattr(
        "gardenos.auth.controller.deliver_token",
        lambda kind, email, token: box.sent.append((kind, email, token)),
    )
    return box


# ---- helpers ----------------------------------------------------------------


def signup(client, email=EMAIL, password=PASSWORD, **extra):
    return client.post("/api/auth/register", json={"email": email, "password": password, **extra})


def login(client, email=EMAIL, password=PASSWORD):
    return client.post("/api/auth/login", json={"email": email, "password": password})


def verify(client, token):
    return client.post("/api/auth/verify-email", json={"token": token})


def refresh(client, token):
    return client.post("/api/auth/refresh", json={"refresh_token": token})


def bearer(access_token: str) -> dict:
    return {"Authorization": f"Bearer {access_token}"}


def error_code(response) -> str:
    return response.get_json()["error"]["code"]


@pytest.fixture
def verified(client, mailbox):
    """A registered and verified account."""
    assert signup(client).status_code == 201
    assert verify(client, mailbox.last("email_verification")).status_code == 200


@pytest.fixture
def session(client, verified) -> dict:
    """Tokens of a freshly logged-in verified user."""
    response = login(client)
    assert response.status_code == 200
    return response.get_json()


# ---- register ---------------------------------------------------------------


def test_register_creates_unverified_account_and_never_stores_the_password(client, mailbox, db):
    response = signup(client, name="Ana", username="ana")

    assert response.status_code == 201
    assert response.get_json()["user"]["email"] == EMAIL
    assert PASSWORD not in response.get_data(as_text=True)

    [(is_verified, password_hash)] = db("SELECT is_verified, password_hash FROM auth")
    assert is_verified is False
    assert password_hash != PASSWORD and password_hash.startswith("$2")
    assert len(mailbox.tokens("email_verification")) == 1


def test_register_stores_only_a_hash_of_the_verification_token(client, mailbox, db):
    signup(client)

    [(stored,)] = db("SELECT token_hash FROM user_token")
    assert stored != mailbox.last("email_verification")


def test_register_normalizes_the_email(client, db):
    assert signup(client, email="  Ana@Example.COM ").status_code == 201

    assert db("SELECT email FROM auth")[0][0] == EMAIL


def test_register_rejects_a_duplicate_email_even_with_different_case(client):
    signup(client)

    response = signup(client, email="ANA@example.com")

    assert response.status_code == 409
    assert error_code(response) == "email_taken"


def test_register_rejects_a_duplicate_username_and_leaves_no_partial_rows(client, db):
    signup(client, username="ana")

    response = signup(client, email="other@example.com", username="ana")

    assert response.status_code == 409
    assert error_code(response) == "username_taken"
    # all-or-nothing: no orphan user / token left by the failed attempt
    assert db("SELECT count(*) FROM users")[0][0] == 1
    assert db("SELECT count(*) FROM user_token")[0][0] == 1


@pytest.mark.parametrize(
    "payload, code",
    [
        ({}, "missing_fields"),
        ({"email": EMAIL}, "missing_fields"),
        ({"email": "not-an-email", "password": PASSWORD}, "invalid_email"),
        ({"email": EMAIL, "password": "short"}, "invalid_password"),
        ({"email": EMAIL, "password": "é" * 40}, "invalid_password"),  # 80 bytes > bcrypt's 72
        ({"email": 123, "password": PASSWORD}, "missing_fields"),  # wrong type must not crash
    ],
)
def test_register_validates_input(client, db, payload, code):
    response = client.post("/api/auth/register", json=payload)

    assert response.status_code == 400
    assert error_code(response) == code
    assert db("SELECT count(*) FROM users")[0][0] == 0


def test_register_with_a_non_object_body_is_a_400_not_a_500(client):
    response = client.post("/api/auth/register", data="[1, 2]", content_type="application/json")

    assert response.status_code == 400


# ---- email verification -----------------------------------------------------


def test_login_is_blocked_until_the_email_is_verified(client, mailbox):
    signup(client)

    blocked = login(client)
    assert blocked.status_code == 403
    assert error_code(blocked) == "email_not_verified"

    assert verify(client, mailbox.last("email_verification")).status_code == 200
    assert login(client).status_code == 200


def test_unverified_account_with_wrong_password_gets_invalid_credentials(client):
    # Otherwise "403 email_not_verified" would confirm that the email is registered.
    signup(client)

    response = login(client, password="wrong-password-1")

    assert response.status_code == 401
    assert error_code(response) == "invalid_credentials"


def test_verification_token_is_single_use(client, mailbox):
    signup(client)
    token = mailbox.last("email_verification")

    assert verify(client, token).status_code == 200
    again = verify(client, token)

    assert again.status_code == 400
    assert error_code(again) == "invalid_token"


def test_expired_verification_token_is_refused(client, mailbox, db):
    signup(client)
    db("UPDATE user_token SET expires_at = now() - interval '1 minute'")

    assert verify(client, mailbox.last("email_verification")).status_code == 400
    assert db("SELECT is_verified FROM auth")[0][0] is False


def test_unknown_verification_token_is_refused(client):
    assert verify(client, "does-not-exist").status_code == 400
    assert verify(client, "").status_code == 400


def test_a_password_reset_token_cannot_verify_an_email(client, mailbox):
    signup(client)
    client.post("/api/auth/forgot-password", json={"email": EMAIL})

    assert verify(client, mailbox.last("password_reset")).status_code == 400


# ---- login ------------------------------------------------------------------


def test_login_returns_tokens_and_stores_only_the_refresh_hash(client, verified, db):
    response = login(client)
    body = response.get_json()

    assert response.status_code == 200
    assert body["token_type"] == "Bearer"
    assert body["expires_in"] > 0
    assert body["access_token"] and body["refresh_token"]

    [(stored,)] = db("SELECT token_hash FROM refresh_token")
    assert stored != body["refresh_token"]
    assert db("SELECT last_login FROM auth")[0][0] is not None


def test_login_normalizes_the_email(client, verified):
    assert login(client, email="  ANA@example.com ").status_code == 200


def test_wrong_password_and_unknown_email_are_indistinguishable(client, verified):
    wrong_password = login(client, password="wrong-password-1")
    unknown_email = login(client, email="nobody@example.com")

    assert wrong_password.status_code == unknown_email.status_code == 401
    assert wrong_password.get_json() == unknown_email.get_json()


def test_inactive_account_cannot_log_in(client, verified, db):
    db("UPDATE auth SET is_active = false")

    response = login(client)

    assert response.status_code == 401
    assert error_code(response) == "invalid_credentials"


def test_login_requires_both_fields(client):
    assert client.post("/api/auth/login", json={"email": EMAIL}).status_code == 400


# ---- /me and access tokens --------------------------------------------------


def test_me_requires_a_valid_access_token(client, session):
    assert client.get("/api/me").status_code == 401
    assert client.get("/api/me", headers=bearer("garbage")).status_code == 401
    # the refresh token is not an access token
    assert client.get("/api/me", headers=bearer(session["refresh_token"])).status_code == 401


def test_me_for_a_user_without_company(client, session):
    response = client.get("/api/me", headers=bearer(session["access_token"]))

    assert response.status_code == 200
    body = response.get_json()
    assert body["memberships"] == []
    assert body["customer_links"] == []
    assert "password" not in response.get_data(as_text=True)


def test_me_lists_the_company_membership(client, session, db):
    db("INSERT INTO company (name, currency, timezone) VALUES ('Verde SL', 'EUR', 'Europe/Madrid')")
    db("INSERT INTO employee (user_id, company_id, permission) "
       "SELECT u.id, c.id, 'owner' FROM users u, company c")

    body = client.get("/api/me", headers=bearer(session["access_token"])).get_json()

    [membership] = body["memberships"]
    assert membership["company"]["name"] == "Verde SL"
    assert membership["permission"] == "owner"


def test_tampered_access_token_is_refused(client, session):
    token = session["access_token"]
    tampered = token[:-2] + ("AA" if not token.endswith("AA") else "BB")

    assert client.get("/api/me", headers=bearer(tampered)).status_code == 401


def test_expired_access_token_is_refused(client, session, monkeypatch):
    from config.config import settings

    monkeypatch.setattr(settings, "ACCESS_TOKEN_MINUTES", -1)  # everything is already expired

    assert client.get("/api/me", headers=bearer(session["access_token"])).status_code == 401


def test_deactivating_a_user_takes_effect_immediately(client, session, db):
    headers = bearer(session["access_token"])
    assert client.get("/api/me", headers=headers).status_code == 200

    db("UPDATE auth SET is_active = false")

    assert client.get("/api/me", headers=headers).status_code == 401


# ---- refresh tokens ---------------------------------------------------------


def test_refresh_rotates_the_token(client, session, db):
    first = session["refresh_token"]

    response = refresh(client, first)
    second = response.get_json()["refresh_token"]

    assert response.status_code == 200
    assert second != first
    assert client.get("/api/me", headers=bearer(response.get_json()["access_token"])).status_code == 200
    # the old row is revoked, the new one is in the SAME family
    assert db("SELECT count(*) FROM refresh_token WHERE revoked_at IS NOT NULL")[0][0] == 1
    assert db("SELECT count(DISTINCT family_id) FROM refresh_token")[0][0] == 1
    assert refresh(client, second).status_code == 200


def test_reusing_a_rotated_refresh_token_revokes_the_whole_family(client, session):
    stolen = session["refresh_token"]
    legit = refresh(client, stolen).get_json()["refresh_token"]

    replay = refresh(client, stolen)

    assert replay.status_code == 401
    assert error_code(replay) == "invalid_refresh_token"
    # the legitimate descendant is dead too: the owner must log in again
    assert refresh(client, legit).status_code == 401


def test_reuse_in_one_session_does_not_affect_another_login(client, session):
    other = login(client).get_json()  # a second device = a second family
    refresh(client, session["refresh_token"])

    assert refresh(client, session["refresh_token"]).status_code == 401  # reuse -> family revoked
    assert refresh(client, other["refresh_token"]).status_code == 200


def test_expired_refresh_token_is_refused(client, session, db):
    db("UPDATE refresh_token SET expires_at = now() - interval '1 minute'")

    assert refresh(client, session["refresh_token"]).status_code == 401


def test_unknown_refresh_token_is_refused(client, verified):
    assert refresh(client, "does-not-exist").status_code == 401
    assert refresh(client, "").status_code == 401


def test_deactivated_user_cannot_refresh(client, session, db):
    db("UPDATE auth SET is_active = false")

    assert refresh(client, session["refresh_token"]).status_code == 401


# ---- logout -----------------------------------------------------------------


def test_logout_revokes_the_refresh_token(client, session):
    response = client.post("/api/auth/logout", json={"refresh_token": session["refresh_token"]})

    assert response.status_code == 204
    assert refresh(client, session["refresh_token"]).status_code == 401


def test_logout_only_ends_that_session(client, session):
    other = login(client).get_json()

    client.post("/api/auth/logout", json={"refresh_token": session["refresh_token"]})

    assert refresh(client, other["refresh_token"]).status_code == 200


def test_logout_is_idempotent(client, session):
    assert client.post("/api/auth/logout", json={"refresh_token": "unknown"}).status_code == 204
    assert client.post("/api/auth/logout", json={}).status_code == 204


# ---- password reset ---------------------------------------------------------


def test_forgot_password_answers_the_same_for_known_and_unknown_emails(client, verified, mailbox, db):
    known = client.post("/api/auth/forgot-password", json={"email": EMAIL})
    unknown = client.post("/api/auth/forgot-password", json={"email": "nobody@example.com"})

    assert known.status_code == unknown.status_code == 202
    assert known.get_json() == unknown.get_json()
    # but only the real account got a token and an email
    assert len(mailbox.tokens("password_reset")) == 1
    assert db("SELECT count(*) FROM user_token WHERE purpose = 'password_reset'")[0][0] == 1


def test_forgot_password_without_an_email_is_still_202(client):
    assert client.post("/api/auth/forgot-password", json={}).status_code == 202


def test_reset_password_changes_the_password(client, verified, mailbox):
    client.post("/api/auth/forgot-password", json={"email": EMAIL})

    response = client.post("/api/auth/reset-password",
                           json={"token": mailbox.last("password_reset"), "password": "brand-new-pass-1"})

    assert response.status_code == 200
    assert login(client, password=PASSWORD).status_code == 401
    assert login(client, password="brand-new-pass-1").status_code == 200


def test_reset_token_is_single_use(client, verified, mailbox):
    client.post("/api/auth/forgot-password", json={"email": EMAIL})
    token = mailbox.last("password_reset")
    client.post("/api/auth/reset-password", json={"token": token, "password": "brand-new-pass-1"})

    again = client.post("/api/auth/reset-password", json={"token": token, "password": "another-pass-22"})

    assert again.status_code == 400
    assert error_code(again) == "invalid_token"
    assert login(client, password="brand-new-pass-1").status_code == 200


def test_expired_reset_token_is_refused(client, verified, mailbox, db):
    client.post("/api/auth/forgot-password", json={"email": EMAIL})
    db("UPDATE user_token SET expires_at = now() - interval '1 minute' WHERE purpose = 'password_reset'")

    response = client.post("/api/auth/reset-password",
                           json={"token": mailbox.last("password_reset"), "password": "brand-new-pass-1"})

    assert response.status_code == 400
    assert login(client).status_code == 200  # old password still valid


def test_a_weak_new_password_does_not_burn_the_token(client, verified, mailbox):
    client.post("/api/auth/forgot-password", json={"email": EMAIL})
    token = mailbox.last("password_reset")

    weak = client.post("/api/auth/reset-password", json={"token": token, "password": "short"})
    retry = client.post("/api/auth/reset-password", json={"token": token, "password": "brand-new-pass-1"})

    assert weak.status_code == 400 and error_code(weak) == "invalid_password"
    assert retry.status_code == 200


def test_an_email_verification_token_cannot_reset_a_password(client, mailbox):
    signup(client)

    response = client.post("/api/auth/reset-password",
                           json={"token": mailbox.last("email_verification"), "password": "brand-new-pass-1"})

    assert response.status_code == 400


def test_reset_password_logs_out_every_session(client, session, mailbox):
    client.post("/api/auth/forgot-password", json={"email": EMAIL})
    client.post("/api/auth/reset-password",
                json={"token": mailbox.last("password_reset"), "password": "brand-new-pass-1"})

    assert refresh(client, session["refresh_token"]).status_code == 401


# ---- rate limiting ----------------------------------------------------------


def test_login_is_limited_per_account(client, verified, limiter_off):
    limiter_off.enabled = True

    for _ in range(5):
        assert login(client, password="wrong-password-1").status_code == 401

    blocked = login(client, password="wrong-password-1")
    assert blocked.status_code == 429
    assert error_code(blocked) == "rate_limited"
    assert "Retry-After" in blocked.headers
    # even the right password is refused while the account is throttled
    assert login(client).status_code == 429
    # another account (same IP) is not affected by this account's bucket
    assert login(client, email="someone-else@example.com").status_code == 401


def test_login_account_bucket_ignores_email_case_and_spaces(client, verified, limiter_off):
    limiter_off.enabled = True

    for email in ["ana@example.com", "ANA@example.com", " Ana@Example.com ", "ana@EXAMPLE.com", "ana@example.com"]:
        login(client, email=email, password="wrong-password-1")

    assert login(client, email="ANA@EXAMPLE.COM", password="wrong-password-1").status_code == 429


def test_login_is_limited_per_ip(client, limiter_off):
    limiter_off.enabled = True

    statuses = [login(client, email=f"user{i}@example.com").status_code for i in range(21)]

    assert statuses[:20] == [401] * 20
    assert statuses[20] == 429


def test_forgot_password_is_limited_per_account(client, verified, mailbox, limiter_off):
    limiter_off.enabled = True

    for _ in range(3):
        assert client.post("/api/auth/forgot-password", json={"email": EMAIL}).status_code == 202

    assert client.post("/api/auth/forgot-password", json={"email": EMAIL}).status_code == 429
    assert len(mailbox.tokens("password_reset")) == 3  # no 4th email: that is the point
