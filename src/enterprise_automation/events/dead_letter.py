from dataclasses import dataclass

@dataclass(frozen=True)
class DeadLetter:
    work_id: str
    reason: str
    payload: dict
