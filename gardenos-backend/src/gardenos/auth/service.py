import hashlib
import logging
import secrets
import uuid
from dataclasses import dataclass
from datetime import timezone, datetime, timedelta

from flask_bcrypt import Bcrypt
from itsdangerous import BadData, URLSafeTimedSerializer
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from config.config import settings, engine
from gardenos.auth.models import Auth, User, UserToken, RefreshToken, TokenPurpose
# Imported from gardenos.models so that EVERY model is registered; Employee's
# relationships reference other modules' models by name.
from gardenos.models import Employee

from .errors import (
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

logger = logging.getLogger(__name__)

# Not bound to an app: hashing needs no app context, only the default cost factor.
bcrypt = Bcrypt()

MIN_PASSWORD_LENGTH = 8
# bcrypt only reads the first 72 bytes (and bcrypt 5 raises above that), so refuse
# longer passwords instead of silently truncating them.
MAX_PASSWORD_BYTES = 72

_access_serializer = URLSafeTimedSerializer(settings.SECRET_KEY, salt="gardenos-access-token")


def hash_password(password: str) -> str:
    return bcrypt.generate_password_hash(password).decode('utf-8')

def verify_hashed_password(password: str, password_hashed: str) -> bool:
    return bcrypt.check_password_hash(password_hashed, password)

# Checked when the email does not exist, so "unknown email" costs the same time as
# "wrong password" and response timing does not reveal which emails are registered.
_DUMMY_HASH = hash_password("gardenos-dummy-password")

def hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode('utf-8')).hexdigest()

def generate_secure_token() -> tuple[str, str]:
    raw_token = secrets.token_urlsafe(32)
    return raw_token, hash_token(raw_token)

def validate_password(password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise InvalidPasswordLengthError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters")
    if len(password.encode('utf-8')) > MAX_PASSWORD_BYTES:
        raise InvalidPasswordLengthError(f"Password must be at most {MAX_PASSWORD_BYTES} bytes")

def create_access_token(user_public_id: uuid.UUID) -> str:
    """Signed, expiring token. Stateless: it carries only the user's public id.
    Company and permission are looked up in the DB on every request (see auth-workflow.md)."""
    return _access_serializer.dumps({"sub": str(user_public_id)})

def read_access_token(token: str) -> uuid.UUID | None:
    """Returns the user's public id, or None if the token is forged, malformed or expired."""
    try:
        data = _access_serializer.loads(token, max_age=settings.ACCESS_TOKEN_MINUTES * 60)
        return uuid.UUID(data["sub"])
    except (BadData, KeyError, TypeError, ValueError):
        return None


@dataclass(frozen=True)
class Tokens:
    access_token: str
    refresh_token: str
    expires_in: int  # access token lifetime, seconds


def _issue_tokens(session: Session, user: User, family_id: uuid.UUID, now: datetime) -> Tokens:
    """Adds a new refresh token (in `family_id`) to the session and signs an access token."""
    raw_refresh, refresh_hash = generate_secure_token()

    session.add(RefreshToken(
        user_id = user.id,
        token_hash = refresh_hash,
        family_id = family_id,
        expires_at = now + timedelta(days = settings.REFRESH_TOKEN_DAYS)
    ))

    return Tokens(
        access_token = create_access_token(user.public_id),
        refresh_token = raw_refresh,
        expires_in = settings.ACCESS_TOKEN_MINUTES * 60,
    )

def _consume_user_token(session: Session, raw_token: str, purpose: TokenPurpose, now: datetime) -> UserToken:
    """Finds a valid one-time token and marks it used. Raises InvalidTokenError otherwise."""
    stmt = select(UserToken).where(
        UserToken.token_hash == hash_token(raw_token),
        UserToken.purpose == purpose,
    ).with_for_update()  # row lock: two concurrent requests cannot both use the same token
    token_entry = session.scalars(stmt).first()

    if not token_entry or token_entry.used_at or token_entry.expires_at < now:
        raise InvalidTokenError("Token is invalid, already used or expired.")

    token_entry.used_at = now
    return token_entry

def _revoke_family(session: Session, family_id: uuid.UUID, now: datetime) -> None:
    session.execute(
        update(RefreshToken)
        .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at = now)
    )


class AuthService:

    @staticmethod
    def register(props: dict) -> tuple[Auth, str]:
        """
            Registers user and generates an email verification UserToken.
            Returns: (auth_record, user_raw_verification_token)
        """
        raw_email = props.get("email")
        password = props.get("password")

        if not raw_email or not password:
            raise EmptyCredentialsError("Email and password are required.")

        normalized_email = raw_email.strip().lower()

        if '@' not in normalized_email:
            raise InvalidEmailFormatError("Invalid email format.")

        validate_password(password)
        hashed_password = hash_password(password)

        try:
            # expire_on_commit=False: the returned objects stay readable after the session closes
            with Session(engine, expire_on_commit = False) as session:
                user = User(
                    name = props.get("name"),
                    surname = props.get("surname"),
                    username = props.get("username"),
                    location = props.get("location")
                )

                auth_user = Auth(
                    user = user,
                    email = normalized_email,
                    password_hash = hashed_password,
                    is_active = True,
                    is_verified = False,
                )

                # Generate Email verification token
                raw_token, token_hash = generate_secure_token()

                verification_token = UserToken(
                    user = user,
                    purpose = TokenPurpose.EMAIL_VERIFICATION,
                    token_hash = token_hash,
                    expires_at = datetime.now(timezone.utc) + timedelta(hours = 24)
                )

                # user is saved through its relationships; one commit = all or nothing
                session.add_all([auth_user, verification_token])
                session.commit()

                return auth_user, raw_token

        except IntegrityError as e:
            # The constraint name tells us which unique rule was broken
            constraint = getattr(getattr(e.orig, "diag", None), "constraint_name", None)
            if constraint == "uq_auth_email":
                raise EmailAlreadyRegisteredError("An account with this email already exists.") from e
            if constraint == "uq_users_username":
                raise UsernameTakenError("This username is already taken.") from e
            raise

    @staticmethod
    def verify_email(raw_token: str) -> None:
        now = datetime.now(timezone.utc)

        with Session(engine) as session:
            token_entry = _consume_user_token(session, raw_token, TokenPurpose.EMAIL_VERIFICATION, now)

            auth_record = session.scalars(
                select(Auth).where(Auth.user_id == token_entry.user_id)
            ).one()
            auth_record.is_verified = True

            session.commit()

    @staticmethod
    def login(email: str, password: str) -> Tokens:
        """
            Verifies user credentials and email verification before generating
            a RefreshToken, returning the access + refresh tokens
        """
        if not email or not password:
            raise EmptyCredentialsError("Email and password are required.")

        normalized_email = email.strip().lower()
        now = datetime.now(timezone.utc)

        with Session(engine) as session:
            stmt = select(Auth).where(Auth.email == normalized_email)
            auth_record = session.scalars(stmt).first()

            # Always run one bcrypt check, even for unknown emails (see _DUMMY_HASH)
            password_ok = verify_hashed_password(
                password, auth_record.password_hash if auth_record else _DUMMY_HASH
            )

            if not auth_record or not auth_record.is_active or not password_ok:
                logger.info("Login failed: bad credentials or inactive account.")
                raise InvalidCredentialsError("Incorrect email or password.")

            # Only reached with the right password, so this does not leak which emails exist
            if not auth_record.is_verified:
                logger.info("Login blocked: email not verified.")
                raise UnverifiedAccountError("Email verification required.")

            auth_record.last_login = now

            # A new login starts a new token family
            tokens = _issue_tokens(session, auth_record.user, uuid.uuid4(), now)
            session.commit()

            return tokens

    @staticmethod
    def refresh(raw_refresh_token: str) -> Tokens:
        """
            Rotation: the presented refresh token is revoked and replaced by a new one
            in the same family. Presenting an already-revoked token means it leaked,
            so the whole family is revoked.
        """
        now = datetime.now(timezone.utc)

        with Session(engine) as session:
            stmt = select(RefreshToken).where(
                RefreshToken.token_hash == hash_token(raw_refresh_token)
            ).with_for_update()
            token_entry = session.scalars(stmt).first()

            if not token_entry:
                raise InvalidRefreshTokenError("Invalid refresh token.")

            if token_entry.revoked_at is not None:
                logger.warning("Refresh token reuse detected: revoking family.")
                _revoke_family(session, token_entry.family_id, now)
                session.commit()  # commit BEFORE raising, or the revocation is rolled back
                raise InvalidRefreshTokenError("Invalid refresh token.")

            if token_entry.expires_at < now:
                raise InvalidRefreshTokenError("Invalid refresh token.")

            auth_record = session.scalars(
                select(Auth).where(Auth.user_id == token_entry.user_id)
            ).one()

            if not auth_record.is_active:
                _revoke_family(session, token_entry.family_id, now)
                session.commit()
                raise InvalidRefreshTokenError("Invalid refresh token.")

            token_entry.revoked_at = now
            tokens = _issue_tokens(session, auth_record.user, token_entry.family_id, now)
            session.commit()

            return tokens

    @staticmethod
    def logout(raw_refresh_token: str) -> None:
        """Revokes the session's whole token family. Idempotent: unknown tokens are ignored."""
        now = datetime.now(timezone.utc)

        with Session(engine) as session:
            token_entry = session.scalars(
                select(RefreshToken).where(RefreshToken.token_hash == hash_token(raw_refresh_token))
            ).first()

            if token_entry:
                _revoke_family(session, token_entry.family_id, now)
                session.commit()

    @staticmethod
    def request_password_reset(email: str) -> str | None:
        """
            Generates a password reset UserToken if the mail exists.
            Returns the raw token to be emailed, or None if the user not found.
            The caller must answer the same way in both cases (no email enumeration).
        """
        normalized_email = email.strip().lower()

        with Session(engine) as session:
            auth_record = session.scalars(
                select(Auth).where(Auth.email == normalized_email)
            ).first()

            if not auth_record or not auth_record.is_active:
                logger.info("Password reset requested for unknown or inactive account.")
                return None

            raw_token, token_hash = generate_secure_token()

            reset_token = UserToken(
                user_id = auth_record.user_id,
                purpose = TokenPurpose.PASSWORD_RESET,
                token_hash = token_hash,
                expires_at = datetime.now(timezone.utc) + timedelta(minutes = 30)
            )

            session.add(reset_token)
            session.commit()

            return raw_token # Send it in an email

    @staticmethod
    def reset_password(raw_token: str, new_password: str) -> None:
        """
            Validate the reset token, update user's password and end all their sessions
        """
        validate_password(new_password)
        now = datetime.now(timezone.utc)

        with Session(engine) as session:
            token_entry = _consume_user_token(session, raw_token, TokenPurpose.PASSWORD_RESET, now)

            auth_record = session.scalars(
                select(Auth).where(Auth.user_id == token_entry.user_id)
            ).one()
            auth_record.password_hash = hash_password(new_password)

            # Whoever knew the old password (maybe an attacker) must be logged out everywhere
            session.execute(
                update(RefreshToken)
                .where(RefreshToken.user_id == token_entry.user_id, RefreshToken.revoked_at.is_(None))
                .values(revoked_at = now)
            )

            session.commit()

    @staticmethod
    def get_user_from_access_token(token: str) -> User | None:
        """
            Resolves a Bearer token to the user, or None. The account is re-checked in
            the DB each time, so deactivating a user takes effect immediately.
        """
        public_id = read_access_token(token)
        if public_id is None:
            return None

        with Session(engine) as session:
            return session.scalars(
                select(User)
                .join(Auth, Auth.user_id == User.id)
                .where(User.public_id == public_id, Auth.is_active.is_(True))
            ).first()

    @staticmethod
    def get_memberships(user_id: int) -> list[dict]:
        """Companies the user works for, with their permission (one at most in the MVP)."""
        with Session(engine) as session:
            employees = session.scalars(
                select(Employee).where(Employee.user_id == user_id).options(joinedload(Employee.company))
            ).all()

            return [
                {
                    "company": {"id": str(e.company.public_id), "name": e.company.name},
                    "permission": e.permission,
                }
                for e in employees
            ]
