"""Synthetic CP3 local API, separate operation and review scopes."""
import os
from pathlib import Path
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from enterprise_automation.governance.queue import LocalQueue
from enterprise_automation.governance.security import authorize, LocalRateLimiter

router = APIRouter(prefix='/cp3', tags=['cp3-local-synthetic'])
limiter = LocalRateLimiter(max_requests=30)


class SubmitEvent(BaseModel):
    model_config = ConfigDict(extra='forbid')
    event_id: str = Field(min_length=1, max_length=64)
    source: str
    record_ref: str = Field(min_length=1, max_length=64)
    scenario: str
    reason_code: str


class Decide(BaseModel):
    model_config = ConfigDict(extra='forbid')
    decision: str
    tick: int = Field(ge=0, le=1_000_000)


def _storage(scope: str, provided: str | None) -> Path:
    authorize(provided, scope)
    limiter.enforce(scope)
    root = os.environ.get('PROJECT15_ROOT', '')
    if not root or not Path(root).is_dir():
        raise HTTPException(503, 'PROJECT15_ROOT is not configured')
    return Path(root).resolve() / 'artifacts' / 'cp3_local_api_queue.sqlite'


@router.post('/event')
def submit_event(payload: SubmitEvent, x_api_key: str | None = Header(default=None)):
    path = _storage('operator', x_api_key)
    with_queue = LocalQueue(path)
    try:
        try:
            return {'result': with_queue.enqueue(payload.model_dump())}
        except ValueError as exc:
            raise HTTPException(422, 'Invalid or conflicting synthetic event') from exc
    finally:
        with_queue.close()


@router.post('/process')
def process_event(tick: int = 0, x_api_key: str | None = Header(default=None)):
    path = _storage('operator', x_api_key)
    if not 0 <= tick <= 1_000_000:
        raise HTTPException(422, 'Invalid logical tick')
    queue = LocalQueue(path)
    try:
        return {'result':queue.process_one(tick)}
    finally:
        queue.close()


@router.post('/review/{event_id}')
def review_event(event_id: str, payload: Decide, x_api_key: str | None = Header(default=None)):
    path = _storage('reviewer', x_api_key)
    queue = LocalQueue(path)
    try:
        try:
            return {'result':queue.decide(event_id, payload.decision, payload.tick)}
        except ValueError as exc:
            raise HTTPException(409, 'Review decision rejected') from exc
    finally:
        queue.close()


@router.get('/metrics')
def get_metrics(x_api_key: str | None = Header(default=None)):
    path = _storage('operator', x_api_key)
    queue = LocalQueue(path)
    try:
        return queue.snapshot()
    finally:
        queue.close()


@router.get('/events')
def page_events(offset: int = 0, limit: int = 20,
                x_api_key: str | None = Header(default=None)):
    path = _storage('operator', x_api_key)
    queue = LocalQueue(path)
    try:
        try:
            return queue.page(offset=offset,limit=limit)
        except ValueError as exc:
            raise HTTPException(422, 'Invalid pagination') from exc
    finally:
        queue.close()
