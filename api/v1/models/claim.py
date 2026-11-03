from enum import StrEnum

COLLECTION_NAME = "Claims"


class ClaimStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
