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
    # A claim was approved and the item is waiting to be collected. Not public.
    CLAIMED = "claimed"
    # Withdrawn by its reporter, or removed by an admin (inappropriate/duplicate). Final.
    CLOSED = "closed"
    RESOLVED = "resolved"
    REJECTED = "rejected"


# Statuses that are approved by an admin and not yet closed, i.e. publicly searchable.
PUBLIC_STATUSES = (ItemStatus.ACTIVE.value, ItemStatus.MATCHED.value)


# Statuses an owner may still edit or close, and an admin may close.
OPEN_STATUSES = ("pending", "active", "matched")


class CloseReason(StrEnum):
    FOUND_IT = "found_it"
    NO_LONGER_NEEDED = "no_longer_needed"
    OTHER = "other"
    REMOVED_BY_ADMIN = "removed_by_admin"
    DUPLICATE = "duplicate"


class ItemCondition(StrEnum):
    GOOD = "Good"
    USED = "Used"
    DAMAGED = "Damaged"


class HandedTo(StrEnum):
    STILL_HAVE_IT = "I still have it"
    SECURITY_OFFICE = "Security office"
    LIBRARY_FRONT_DESK = "Library front desk"
    OTHER_OFFICE = "Other office"
