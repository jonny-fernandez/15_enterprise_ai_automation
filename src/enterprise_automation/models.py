from pydantic import BaseModel, Field

class WorkItem(BaseModel):
    work_id: str
    source_system: str
    payload: dict
    attempt: int = 0
    status: str = "new"

class WorkflowResult(BaseModel):
    work_id: str
    status: str
    actions: list[str] = Field(default_factory=list)
    needs_human_review: bool = False
