
class AuthError(Exception):
    """Base exception for authentication failures."""
    pass

class EmptyCredentialsError(AuthError):
    """Raised when email or password is missing."""
    pass

class InvalidEmailFormatError(AuthError):
    """Raised when the email format is invalid."""
    pass

class InvalidPasswordLengthError(AuthError):
    """Raised when password length is below required minimum."""
    pass

class UserNotFoundError(AuthError):
    """Raised when no user matches the given email."""
    pass

class MultipleUsersFoundError(AuthError):
    """Raised when database consistency is violated (duplicate emails)."""
    pass

class InvalidPasswordError(AuthError):
    """Raised when the provided password does not match the hash."""
    pass

class UnverifiedAccountError(AuthError):
    """Raise when user wants to log in after register but he didn't confirm the email msg"""
    pass

class InvalidCredentialsError(AuthError):
    """Login failed. Deliberately does not say whether the email or the password was wrong."""
    pass

class EmailAlreadyRegisteredError(AuthError):
    """Raised when registering an email that already has an account."""
    pass

class UsernameTakenError(AuthError):
    """Raised when registering a username that is already in use."""
    pass

class InvalidTokenError(AuthError):
    """One-time token (email verification / password reset) is unknown, used or expired."""
    pass

class InvalidRefreshTokenError(AuthError):
    """Refresh token is unknown, expired, revoked or its family was revoked after reuse."""
    pass