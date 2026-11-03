from enum import StrEnum

COLLECTION_NAME = "Items"
IMAGES_COLLECTION_NAME = "ItemImages"


class ReportType(StrEnum):
    LOST = "lost"
    FOUND = "found"


class ItemStatus(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    MATCHED = "matched"
    RESOLVED = "resolved"
    REJECTED = "rejected"


# Statuses that are approved by an admin and not yet closed, i.e. publicly searchable.
PUBLIC_STATUSES = (ItemStatus.ACTIVE.value, ItemStatus.MATCHED.value)


class ItemCondition(StrEnum):
    GOOD = "Good"
    USED = "Used"
    DAMAGED = "Damaged"


class HandedTo(StrEnum):
    STILL_HAVE_IT = "I still have it"
    SECURITY_OFFICE = "Security office"
    LIBRARY_FRONT_DESK = "Library front desk"
    OTHER_OFFICE = "Other office"
