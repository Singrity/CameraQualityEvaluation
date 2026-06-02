from pydantic import BaseModel
from typing import Optional, Literal

JobStatus = Literal["pending", "processing", "completed", "failed"]

class Job(BaseModel):
    id: str
    status: JobStatus = "pending"
    result: Optional[dict] = None
    img_paths: list[str] = []
    error: Optional[str] = None