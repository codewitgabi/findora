from enum import StrEnum

COLLECTION_NAME = "AuditLogs"


class AuditTargetType(StrEnum):
    CLAIM = "claim"
    REPORT = "report"
    USER = "user"
    CATEGORY = "category"
