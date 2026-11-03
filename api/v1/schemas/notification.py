from datetime import datetime

from pydantic import BaseModel

from api.v1.models.notification import NotificationType


class NotificationOut(BaseModel):
    id: str
    type: NotificationType
    title: str
    message: str
    is_read: bool
    created_at: datetime
