from datetime import datetime

from pydantic import BaseModel

from api.v1.models.audit_log import AuditTargetType


class AuditLogOut(BaseModel):
    id: str
    admin_name: str
    action: str
    target_type: AuditTargetType
    target_id: str
    created_at: datetime
