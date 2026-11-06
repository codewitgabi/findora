from enum import StrEnum

COLLECTION_NAME = "Notifications"


class NotificationType(StrEnum):
    MATCH = "match"
    CLAIM = "claim"
    STATUS = "status"
    MESSAGE = "message"
