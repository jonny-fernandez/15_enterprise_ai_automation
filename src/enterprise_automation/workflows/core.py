"""Deterministic local validation; no external system mutations."""
from enterprise_automation.idempotency import IdempotencyStore
from enterprise_automation.models import WorkItem, WorkflowResult
from enterprise_automation.pipelines.ingestion import canonical_json, sha256_text


class WorkflowEngine:
    def __init__(self) -> None:
        self.idempotency = IdempotencyStore()

    def process(self, item: WorkItem) -> WorkflowResult:
        if not item.work_id.strip() or not item.source_system.strip() or not item.payload:
            return WorkflowResult(work_id=item.work_id, status="rejected",
                                  actions=["deterministic_validation"])
        try:
            fingerprint = sha256_text(canonical_json({"source_system": item.source_system,
                                                       "payload": item.payload}))
        except (ValueError, TypeError):
            return WorkflowResult(work_id=item.work_id, status="rejected",
                                  actions=["deterministic_validation"])
        existing = self.idempotency.fingerprint(item.work_id)
        if existing is not None:
            if existing == fingerprint:
                return WorkflowResult(work_id=item.work_id, status="duplicate_skipped", actions=["idempotency_check"])
            return WorkflowResult(work_id=item.work_id, status="conflict_requires_review",
                                  actions=["idempotency_check", "conflict_detected"], needs_human_review=True)
        self.idempotency.mark(item.work_id, fingerprint)
        return WorkflowResult(work_id=item.work_id, status="processed",
                              actions=["deterministic_validation", "idempotency_check"])
