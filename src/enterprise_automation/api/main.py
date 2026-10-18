"""Fail-closed local API. CP12 will formalize enterprise auth and scopes."""
import hmac
import os
from fastapi import FastAPI, Header, HTTPException
from enterprise_automation.models import WorkItem
from enterprise_automation.workflows.core import WorkflowEngine

app = FastAPI(title="Enterprise AI Automation Platform (CP1 local)", version="0.1.0")
engine = WorkflowEngine()


@app.get("/health")
def health():
    return {"status": "ok", "mode": "local_cp1"}


@app.post("/work")
def submit_work(item: WorkItem, x_api_key: str | None = Header(default=None)):
    configured = os.environ.get("PROJECT15_API_KEY", "")
    if not configured:
        raise HTTPException(status_code=503, detail="Work API disabled until an API key is configured")
    if not x_api_key or not hmac.compare_digest(configured, x_api_key):
        raise HTTPException(status_code=401, detail="Unauthorized")
    return engine.process(item)


# CP2: explicitly opt-in local API and event triggers. Same fail-closed local
# API-key boundary as CP1; OAuth, scopes, and rate limiting remain CP3.
from pathlib import Path
from pydantic import BaseModel, Field
from enterprise_automation.pipelines.cp2_pipeline import execute_cp2


class CP2Request(BaseModel):
    source_run_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    run_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    event_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{1,64}$")


def _check_cp2_key(x_api_key: str | None) -> Path:
    configured = os.environ.get("PROJECT15_API_KEY", "")
    if not configured:
        raise HTTPException(status_code=503, detail="CP2 local API disabled")
    if not x_api_key or not hmac.compare_digest(configured, x_api_key):
        raise HTTPException(status_code=401, detail="Unauthorized")
    root = os.environ.get("PROJECT15_ROOT", "")
    if not root or not Path(root).is_dir():
        raise HTTPException(status_code=503, detail="PROJECT15_ROOT is not configured")
    return Path(root).resolve()


def _process_cp2(payload: CP2Request, mode: str, token: str | None):
    root = _check_cp2_key(token)
    from enterprise_automation.cp2_demo import local_spark
    spark = local_spark()
    try:
        return execute_cp2(root=root, source_run_id=payload.source_run_id,
                           run_id=payload.run_id, trigger_mode=mode,
                           trigger_id=payload.event_id or payload.run_id, spark=spark)
    except (ValueError, FileNotFoundError, FileExistsError) as exc:
        # Do not disclose filesystem paths or sensitive content in responses.
        raise HTTPException(status_code=409, detail="Invalid or conflicting local run") from exc
    finally:
        spark.stop()


@app.post("/cp2/run")
def run_local_cp2(payload: CP2Request, x_api_key: str | None = Header(default=None)):
    return _process_cp2(payload, "api", x_api_key)


@app.post("/cp2/event")
def synthetic_event_cp2(payload: CP2Request, x_api_key: str | None = Header(default=None)):
    if payload.event_id is None:
        raise HTTPException(status_code=422, detail="event_id is required")
    return _process_cp2(payload, "event", x_api_key)

# CP3 local synthetic governance API: separate operator/reviewer keys, no cloud.
from enterprise_automation.api.cp3 import router as cp3_router
app.include_router(cp3_router)
