"""Durable, single-worker SQLite queue, retry budget, DLQ and review decisions.

All data is synthetic and local. SQLite serializes local claim/writes; this is
not a distributed broker, nor safe across multiple separate worker hosts.
"""
import json
from pathlib import Path
import sqlite3

from .policy import digest, event_contract, mock_ai_suggestion, validate_ai_suggestion
from .retry import RetryPolicy, SyntheticTransientFailure, SyntheticPermanentFailure


class LocalQueue:
    def __init__(self, path: Path, *, retry: RetryPolicy | None = None):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA busy_timeout=10000")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS events (
                event_id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL,
                payload_json TEXT NOT NULL, status TEXT NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0, next_tick INTEGER NOT NULL DEFAULT 0,
                lease_until INTEGER, error_code TEXT, proposal_json TEXT
            );
            CREATE TABLE IF NOT EXISTS decisions (
                event_id TEXT PRIMARY KEY, decision TEXT NOT NULL,
                evidence_sha256 TEXT NOT NULL, review_tick INTEGER NOT NULL,
                FOREIGN KEY(event_id) REFERENCES events(event_id)
            );
        """)
        self.retry = retry or RetryPolicy()

    def close(self):
        self.db.close()

    def enqueue(self, raw: dict) -> str:
        event = event_contract(raw)
        fp = digest(event)
        self.db.execute("BEGIN IMMEDIATE")
        try:
            row = self.db.execute("SELECT fingerprint FROM events WHERE event_id=?", (event["event_id"],)).fetchone()
            if row:
                if row["fingerprint"] != fp:
                    raise ValueError("Conflicting event ID requires external review")
                outcome = "duplicate_skipped"
            else:
                self.db.execute("INSERT INTO events(event_id,fingerprint,payload_json,status) VALUES(?,?,?,?)",
                    (event["event_id"], fp, json.dumps(event, sort_keys=True), "pending"))
                outcome = "enqueued"
            self.db.commit()
            return outcome
        except BaseException:
            self.db.rollback()
            raise

    def claim(self, tick: int, *, lease_ticks: int = 3) -> dict | None:
        if type(tick) is not int or tick < 0 or type(lease_ticks) is not int or lease_ticks < 1:
            raise ValueError("Invalid logical clock")
        self.db.execute("BEGIN IMMEDIATE")
        try:
            # An abandoned claim becomes eligible at lease expiry; attempts
            # are counted at claim time so a crash cannot reset the budget.
            row = self.db.execute("""SELECT * FROM events WHERE
                (status IN ('pending','retry_wait') AND next_tick<=?)
                OR (status='processing' AND lease_until<=?)
                ORDER BY event_id LIMIT 1""", (tick, tick)).fetchone()
            if not row:
                self.db.commit()
                return None
            if row["attempts"] >= self.retry.max_attempts:
                self.db.execute("UPDATE events SET status='dead_letter',error_code='lease_exhausted',lease_until=NULL WHERE event_id=?", (row["event_id"],))
                self.db.commit()
                return {"event_id": row["event_id"], "status": "dead_letter", "attempts": row["attempts"]}
            self.db.execute("""UPDATE events SET status='processing', attempts=attempts+1,
                lease_until=? WHERE event_id=?""", (tick + lease_ticks, row["event_id"]))
            self.db.commit()
            return {"event_id": row["event_id"], "payload": json.loads(row["payload_json"]),
                    "attempts": row["attempts"]+1, "status": "claimed"}
        except BaseException:
            self.db.rollback()
            raise

    def resolve(self, claim: dict, tick: int, *, outcome: str):
        event_id, attempts = claim["event_id"], claim["attempts"]
        row = self.db.execute("SELECT * FROM events WHERE event_id=?", (event_id,)).fetchone()
        if (not row or row["status"] != "processing" or row["attempts"] != attempts or
                type(tick) is not int or tick < 0 or row["lease_until"] < tick):
            raise ValueError("Stale or invalid queue claim")
        if outcome == "success":
            updates = ("completed", None, None, None)
        elif outcome == "review":
            e = json.loads(row["payload_json"])
            proposal = validate_ai_suggestion(e, mock_ai_suggestion(e))
            updates = ("awaiting_review", None, None, json.dumps(proposal, sort_keys=True))
        elif outcome in {"transient", "timeout"} and attempts < self.retry.max_attempts:
            updates = ("retry_wait", self.retry.next_tick(tick, attempts), outcome, None)
        elif outcome in {"transient", "timeout", "permanent"}:
            updates = ("dead_letter", None, outcome, None)
        else:
            raise ValueError("Unsafe queue outcome")
        self.db.execute("BEGIN IMMEDIATE")
        try:
            # Optimistic state+attempt check prevents double resolution.
            result = self.db.execute("""UPDATE events SET status=?,next_tick=COALESCE(?,next_tick),
                lease_until=NULL,error_code=?,proposal_json=? WHERE event_id=? AND
                status='processing' AND attempts=?""", (*updates, event_id, attempts))
            if result.rowcount != 1:
                raise ValueError("Concurrent claim state changed")
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise
        return updates[0]

    def process_one(self, tick: int) -> dict | None:
        claim = self.claim(tick)
        if claim is None or claim["status"] == "dead_letter":
            return claim
        # Test-only synthetic outcomes; no network or LLM requests.
        scenario = claim["payload"]["scenario"]
        if scenario == "success":
            outcome = "success"
        elif scenario == "review":
            outcome = "review"
        elif scenario == "transient":
            outcome = "transient" if claim["attempts"] < 2 else "success"
        else:
            outcome = "permanent"
        final = self.resolve(claim, tick, outcome=outcome)
        return {"event_id": claim["event_id"], "attempts": claim["attempts"], "status": final}

    def decide(self, event_id: str, decision: str, tick: int) -> str:
        if decision not in {"approve", "reject"} or type(tick) is not int or tick < 0:
            raise ValueError("Invalid decision")
        self.db.execute("BEGIN IMMEDIATE")
        try:
            row = self.db.execute("SELECT * FROM events WHERE event_id=?", (event_id,)).fetchone()
            if not row or row["status"] != "awaiting_review":
                raise ValueError("Review item not awaiting decision")
            event = json.loads(row["payload_json"])
            validate_ai_suggestion(event, json.loads(row["proposal_json"]))
            new_status = "review_approved" if decision == "approve" else "review_rejected"
            self.db.execute("UPDATE events SET status=? WHERE event_id=? AND status='awaiting_review'", (new_status,event_id))
            self.db.execute("INSERT INTO decisions VALUES(?,?,?,?)", (event_id, decision, digest(event), tick))
            self.db.commit()
            return new_status
        except BaseException:
            self.db.rollback()
            raise

    def counts(self) -> dict[str, int]:
        statuses = ("pending", "retry_wait", "processing", "completed", "dead_letter",
                    "awaiting_review", "review_approved", "review_rejected")
        observed = {r["status"]: r["n"] for r in self.db.execute(
            "SELECT status,COUNT(*) as n FROM events GROUP BY status")}
        if any(status not in statuses for status in observed):
            raise ValueError("Unrecognized queue state")
        return {status: observed.get(status, 0) for status in statuses}

    def page(self, *, offset: int = 0, limit: int = 20) -> dict:
        """Read-only pagination; only public synthetic metadata is returned."""
        if (type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 50):
            raise ValueError("Invalid pagination")
        rows = self.db.execute("SELECT event_id,status,attempts FROM events ORDER BY event_id LIMIT ? OFFSET ?",
                               (limit, offset)).fetchall()
        total = self.db.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        return {"items":[dict(r) for r in rows], "total":total,
                "next_offset":offset+len(rows) if offset+len(rows)<total else None}

    def snapshot(self) -> dict:
        return {"schema_version": "cp3.snapshot.v1", "counts": self.counts(),
                "total_events": self.db.execute("SELECT COUNT(*) FROM events").fetchone()[0],
                "total_attempts": self.db.execute("SELECT COALESCE(SUM(attempts),0) FROM events").fetchone()[0],
                "review_decisions": self.db.execute("SELECT COUNT(*) FROM decisions").fetchone()[0]}
