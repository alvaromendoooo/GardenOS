from flask import Blueprint, current_app, g, jsonify, request
from flask_httpauth import HTTPTokenAuth
from flask_limiter.util import get_remote_address

from gardenos.auth.errors import (
    AuthError,
    EmptyCredentialsError,
    InvalidEmailFormatError,
    InvalidPasswordLengthError,
    InvalidCredentialsError,
    EmailAlreadyRegisteredError,
    UsernameTakenError,
    InvalidTokenError,
    InvalidRefreshTokenError,
    UnverifiedAccountError,
)
from gardenos.auth.service import AuthService
from gardenos.shared.limiter import limiter

auth_bp = Blueprint("auth", __name__, url_prefix="/api")

# Protects an endpoint with `Authorization: Bearer <access token>`.
# Other modules use it too:  @token_auth.login_required  +  token_auth.current_user()
token_auth = HTTPTokenAuth(scheme="Bearer")

# AuthError subclass -> (HTTP status, machine-readable code for the frontend)
ERROR_RESPONSES: dict[type[AuthError], tuple[int, str]] = {
    EmptyCredentialsError: (400, "missing_fields"),
    InvalidEmailFormatError: (400, "invalid_email"),
    InvalidPasswordLengthError: (400, "invalid_password"),
    InvalidTokenError: (400, "invalid_token"),
    InvalidCredentialsError: (401, "invalid_credentials"),
    InvalidRefreshTokenError: (401, "invalid_refresh_token"),
    UnverifiedAccountError: (403, "email_not_verified"),
    EmailAlreadyRegisteredError: (409, "email_taken"),
    UsernameTakenError: (409, "username_taken"),
}


def email_key() -> str:
    """Rate-limit bucket per target account: stops many IPs attacking one email."""
    email = get_str(get_body(), "email").strip().lower()
    return email or get_remote_address()

def error_response(status: int, code: str, message: str):
    return jsonify({"error": {"code": code, "message": message}}), status


@auth_bp.errorhandler(AuthError)
def handle_auth_error(e: AuthError):
    status, code = ERROR_RESPONSES.get(type(e), (400, "auth_error"))
    return error_response(status, code, str(e))


@token_auth.verify_token
def verify_token(token: str):
    # Whatever is returned here (truthy) becomes token_auth.current_user()
    return AuthService.get_user_from_access_token(token)


@token_auth.error_handler
def token_auth_error(status: int):
    return error_response(status, "unauthorized", "Missing or invalid access token.")


def get_body() -> dict:
    """JSON body as a dict; anything else (no body, a list, bad JSON) counts as empty."""
    body = request.get_json(silent=True)
    return body if isinstance(body, dict) else {}

def get_str(body: dict, key: str) -> str:
    """A string field, or "" when missing or not a string (so .strip() can never crash)."""
    value = body.get(key)
    return value if isinstance(value, str) else ""

def deliver_token(kind: str, email: str, raw_token: str) -> None:
    # TODO(phase 5): send a real email containing a link with the token.
    # Until then, in debug mode only, the token is logged so flows can be tried by hand.
    if current_app.debug:
        current_app.logger.info("[DEV ONLY] %s token for %s: %s", kind, email, raw_token)


@auth_bp.post("/auth/register")
def register():
    body = get_body()

    auth_record, raw_token = AuthService.register({
        "email": get_str(body, "email"),
        "password": get_str(body, "password"),
        "name": get_str(body, "name") or None,
        "surname": get_str(body, "surname") or None,
        "username": get_str(body, "username") or None,
        "location": get_str(body, "location") or None,
    })

    deliver_token("email_verification", auth_record.email, raw_token)

    return jsonify({
        "user": {"id": str(auth_record.user.public_id), "email": auth_record.email},
        "message": "Account created. Check your email to verify it.",
    }), 201


@auth_bp.post("/auth/verify-email")
def verify_email():
    # POST, not GET: link scanners and prefetchers would consume a one-time token via GET
    AuthService.verify_email(get_str(get_body(), "token"))
    return jsonify({"message": "Email verified."}), 200


@auth_bp.post("/auth/login")
@limiter.limit("20 per minute")  # per IP
@limiter.limit("5 per 15 minutes", key_func=email_key)  # per account
def login():
    body = get_body()
    tokens = AuthService.login(get_str(body, "email"), get_str(body, "password"))

    return jsonify({
        "access_token": tokens.access_token,
        "refresh_token": tokens.refresh_token,
        "token_type": "Bearer",
        "expires_in": tokens.expires_in,
    }), 200


@auth_bp.post("/auth/refresh")
def refresh():
    tokens = AuthService.refresh(get_str(get_body(), "refresh_token"))

    return jsonify({
        "access_token": tokens.access_token,
        "refresh_token": tokens.refresh_token,
        "token_type": "Bearer",
        "expires_in": tokens.expires_in,
    }), 200


@auth_bp.post("/auth/logout")
def logout():
    AuthService.logout(get_str(get_body(), "refresh_token"))
    return "", 204


@auth_bp.post("/auth/forgot-password")
@limiter.limit("10 per hour")  # per IP
@limiter.limit("3 per hour", key_func=email_key)  # per account: no mail-bombing a victim
def forgot_password():
    email = get_str(get_body(), "email")

    raw_token = AuthService.request_password_reset(email) if email else None
    if raw_token:
        deliver_token("password_reset", email, raw_token)

    # Same answer whether or not the email exists, so this cannot be used to find out who is registered
    return jsonify({"message": "If that email is registered, a reset link has been sent."}), 202


@auth_bp.post("/auth/reset-password")
def reset_password():
    body = get_body()
    AuthService.reset_password(get_str(body, "token"), get_str(body, "password"))
    return jsonify({"message": "Password updated. Please log in again."}), 200


@auth_bp.get("/me")
@token_auth.login_required
def me():
    user = token_auth.current_user()

    return jsonify({
        "user": {
            "id": str(user.public_id),
            "name": user.name,
            "surname": user.surname,
            "username": user.username,
            "location": user.location,
        },
        # The frontend picks the area from these (see auth-workflow.md)
        "memberships": AuthService.get_memberships(user.id),
        "customer_links": [],  # client portal is post-MVP
    }), 200
