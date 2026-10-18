from enterprise_automation.models import WorkItem
from enterprise_automation.workflows.core import WorkflowEngine

def test_idempotent_processing():
    engine = WorkflowEngine()
    item = WorkItem(work_id="A1", source_system="ERP", payload={"value": 1})
    first = engine.process(item)
    second = engine.process(item)
    assert first.status == "processed"
    assert second.status == "duplicate_skipped"
