from datetime import datetime
from typing import Optional

from pydantic import BaseModel

from api.v1.models.notification import NotificationType


class NotificationOut(BaseModel):
    id: str
    type: NotificationType
    title: str
    message: str
    is_read: bool
    item_id: Optional[str] = None
    claim_id: Optional[str] = None
    created_at: datetime
