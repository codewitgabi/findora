from pydantic import BaseModel, HttpUrl


class ImageUploadOut(BaseModel):
    url: HttpUrl
    public_id: str
    resource_type: str
