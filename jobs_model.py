from pydantic import BaseModel

class Job(BaseModel):
    id: str
    status: str
    result: dict = None