from __future__ import annotations

from typing import ClassVar


class AuthError(Exception):
    """A safe, stable authentication error exposed at the HTTP boundary."""

    code: ClassVar[str] = "authentication_failed"
    status_code: ClassVar[int] = 401
    public_message: ClassVar[str] = "authentication failed"

    def __init__(self, *, retry_after_seconds: int | None = None) -> None:
        super().__init__(self.public_message)
        self.retry_after_seconds = retry_after_seconds


class AuthenticationRequiredError(AuthError):
    code = "authentication_required"
    public_message = "authentication required"


class InvalidCredentialsError(AuthError):
    code = "invalid_credentials"
    public_message = "invalid credentials"


class InvalidSessionError(AuthError):
    code = "invalid_or_expired_session"
    public_message = "invalid or expired session"


class OriginNotAllowedError(AuthError):
    code = "origin_not_allowed"
    status_code = 403
    public_message = "request origin is not allowed"


class CsrfValidationError(AuthError):
    code = "csrf_failed"
    status_code = 403
    public_message = "CSRF validation failed"


class WorkspaceAccessDeniedError(AuthError):
    code = "workspace_access_denied"
    status_code = 403
    public_message = "workspace access denied"


class SignupDisabledError(AuthError):
    code = "signup_disabled"
    status_code = 403
    public_message = "signup is disabled"


class EmailAlreadyExistsError(AuthError):
    code = "email_already_exists"
    status_code = 409
    public_message = "an account with this email already exists"


class AuthRateLimitedError(AuthError):
    code = "auth_rate_limited"
    status_code = 429
    public_message = "too many authentication attempts"
