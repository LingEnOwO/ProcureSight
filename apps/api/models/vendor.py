from pydantic import BaseModel, Field
from uuid import UUID

class Vendor(BaseModel):
    id: UUID = Field(
        ...,
        example="98681ed3-d1e5-4440-b249-85f181f32b0e",
        description="Vendor UUID"
    )
    name: str = Field(
        ...,
        example="Apex Office Supply",
        description="Display name of the vendor"
    )