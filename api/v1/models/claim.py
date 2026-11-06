from enum import StrEnum

COLLECTION_NAME = "Claims"
MESSAGES_COLLECTION_NAME = "ClaimMessages"


class ClaimStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class HandoverStatus(StrEnum):
    """Derived state of an approved claim's physical handover."""

    AWAITING_PICKUP = "awaiting_pickup"
    COLLECTED = "collected"


class ClaimRole(StrEnum):
    """How a participant relates to a claim. Never exposes identity or contact data."""

    CLAIMANT = "claimant"
    REPORTER = "reporter"
    ADMIN = "admin"
