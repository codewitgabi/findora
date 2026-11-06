from enum import StrEnum

PASSWORD_RESETS_COLLECTION = "PasswordResets"
# One document per rate-limited attempt; a TTL index expires them after the window.
AUTH_ATTEMPTS_COLLECTION = "AuthAttempts"


class AttemptKind(StrEnum):
    FAILED_LOGIN = "failed_login"
    RESET_REQUEST = "reset_request"
