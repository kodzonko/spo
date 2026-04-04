from __future__ import annotations


class SpoError(Exception):
    """Base application error."""


class AuthenticationError(SpoError):
    """Authentication failed or credentials are missing."""


class RateLimitError(SpoError):
    """The remote service asked us to wait before continuing."""

    def __init__(self, message: str, retry_after: int | float | None = None):
        super().__init__(message)
        self.retry_after = retry_after


class UnsupportedOperationError(SpoError):
    """Raised when a service cannot perform an operation."""


class ValidationError(SpoError):
    """Raised for malformed user input."""
