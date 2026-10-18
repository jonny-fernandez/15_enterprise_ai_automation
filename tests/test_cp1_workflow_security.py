from fastapi.testclient import TestClient
from enterprise_automation.api.main import app
from enterprise_automation.models import WorkItem
from enterprise_automation.workflows.core import WorkflowEngine


def test_empty_payload_not_marked_processed():
    engine = WorkflowEngine()
    item = WorkItem(work_id="empty", source_system="ERP", payload={})
    result = engine.process(item)
    assert result.status == "rejected" and not engine.idempotency.seen("empty")


def test_idempotency_conflict_needs_review():
    engine = WorkflowEngine()
    first = engine.process(WorkItem(work_id="same", source_system="ERP", payload={"amount":1}))
    second = engine.process(WorkItem(work_id="same", source_system="ERP", payload={"amount":2}))
    assert first.status == "processed"
    assert second.status == "conflict_requires_review"
    assert second.needs_human_review


def test_idempotency_equivalent_payloads():
    engine = WorkflowEngine()
    assert engine.process(WorkItem(work_id="w", source_system="ERP", payload={"a":1,"b":2})).status == "processed"
    assert engine.process(WorkItem(work_id="w", source_system="ERP", payload={"b":2,"a":1})).status == "duplicate_skipped"


def test_work_endpoint_disabled_without_configured_key(monkeypatch):
    monkeypatch.delenv("PROJECT15_API_KEY", raising=False)
    response = TestClient(app).post("/work", json={"work_id":"w", "source_system":"ERP", "payload":{"a":1}})
    assert response.status_code == 503


def test_work_endpoint_rejects_invalid_key(monkeypatch):
    monkeypatch.setenv("PROJECT15_API_KEY", "local-demo-test-secret")
    response = TestClient(app).post("/work", headers={"X-API-Key":"wrong"},
        json={"work_id":"w", "source_system":"ERP", "payload":{"a":1}})
    assert response.status_code == 401


def test_work_endpoint_works_with_configured_key(monkeypatch):
    monkeypatch.setenv("PROJECT15_API_KEY", "local-demo-test-secret")
    response = TestClient(app).post("/work", headers={"X-API-Key":"local-demo-test-secret"},
        json={"work_id":"test_cp1_http_1", "source_system":"ERP", "payload":{"a":1}})
    assert response.status_code == 200 and response.json()["status"] == "processed"


def test_health_does_not_require_key(monkeypatch):
    monkeypatch.delenv("PROJECT15_API_KEY", raising=False)
    assert TestClient(app).get("/health").json()["status"] == "ok"
