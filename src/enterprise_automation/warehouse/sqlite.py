"""Local SQLite warehouse and durable run/record-version checkpoint store.

No network connections, production data, or credential access. SQLite writes
are transactional; all records are synthetic and remain local-only.
"""
import json
import sqlite3
from datetime import datetime
from pathlib import Path

from enterprise_automation.pipelines.incremental_load import parse_timestamp


class SQLiteWarehouse:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path), timeout=10)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA busy_timeout=10000")
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY, signature TEXT NOT NULL,
                source_run_id TEXT NOT NULL, trigger_mode TEXT NOT NULL,
                trigger_id TEXT NOT NULL, summary_json TEXT NOT NULL
            );
            CREATE UNIQUE INDEX IF NOT EXISTS unique_trigger ON runs(trigger_mode, trigger_id);
            CREATE TABLE IF NOT EXISTS watermarks (
                source_system TEXT PRIMARY KEY, watermark_utc TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS record_versions (
                source_system TEXT NOT NULL, record_id TEXT NOT NULL,
                record_sha256 TEXT NOT NULL,
                PRIMARY KEY (source_system, record_id, record_sha256)
            );
            CREATE TABLE IF NOT EXISTS orders (
                order_id TEXT PRIMARY KEY, customer_id TEXT NOT NULL,
                customer_name TEXT, amount_usd TEXT NOT NULL,
                updated_at_utc TEXT NOT NULL, ticket_count INTEGER NOT NULL,
                reconciliation_status TEXT NOT NULL, source_sha256 TEXT NOT NULL
            );
        """)

    def close(self):
        self.conn.close()

    def existing_run(self, run_id: str):
        return self.conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()

    def existing_trigger(self, trigger_mode: str, trigger_id: str):
        return self.conn.execute("SELECT * FROM runs WHERE trigger_mode=? AND trigger_id=?",
                                 (trigger_mode, trigger_id)).fetchone()

    def watermarks(self) -> dict[str, datetime]:
        return {r["source_system"]: parse_timestamp(r["watermark_utc"], require_timezone=True)
                for r in self.conn.execute("SELECT source_system,watermark_utc FROM watermarks")}

    def known_versions(self) -> set[tuple[str, str, str]]:
        return {(r[0], r[1], r[2]) for r in self.conn.execute(
            "SELECT source_system,record_id,record_sha256 FROM record_versions")}

    def order_count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0]

    def commit_run(self, *, run_id: str, signature: str, source_run_id: str,
                   trigger_mode: str, trigger_id: str, summary: dict,
                   selected_records: dict[str, list[dict]], rows: list[dict]):
        """Atomically upsert warehouse rows, versions, watermarks and run audit."""
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            for row in rows:
                existing = self.conn.execute(
                    "SELECT updated_at_utc,source_sha256 FROM orders WHERE order_id=?",
                    (row["order_id"],)).fetchone()
                if existing:
                    old = parse_timestamp(existing[0], require_timezone=True)
                    new = parse_timestamp(row["updated_at_utc"], require_timezone=True)
                    if new < old:
                        continue  # no regressions on old/late versions
                    if new == old and existing[1] != row["source_sha256"]:
                        raise ValueError("Conflicting order version at same timestamp")
                self.conn.execute("""
                    INSERT INTO orders(order_id,customer_id,customer_name,amount_usd,
                    updated_at_utc,ticket_count,reconciliation_status,source_sha256)
                    VALUES (?,?,?,?,?,?,?,?)
                    ON CONFLICT(order_id) DO UPDATE SET
                    customer_id=excluded.customer_id,customer_name=excluded.customer_name,
                    amount_usd=excluded.amount_usd,updated_at_utc=excluded.updated_at_utc,
                    ticket_count=excluded.ticket_count,
                    reconciliation_status=excluded.reconciliation_status,
                    source_sha256=excluded.source_sha256
                """, (row["order_id"], row["customer_id"], row["customer_name"],
                      row["amount_usd"], row["updated_at_utc"], row["ticket_count"],
                      row["reconciliation_status"], row["source_sha256"]))
            existing_marks = self.watermarks()
            for source, records in selected_records.items():
                for r in records:
                    self.conn.execute("INSERT OR IGNORE INTO record_versions VALUES(?,?,?)",
                                      (source, r["record_id"], r["record_sha256"]))
                candidates = [parse_timestamp(r["payload"]["updated_at_utc"], require_timezone=True)
                              for r in records]
                if candidates:
                    value = max([*candidates, *([existing_marks[source]] if source in existing_marks else [])])
                    self.conn.execute("""INSERT INTO watermarks(source_system,watermark_utc)
                        VALUES (?,?) ON CONFLICT(source_system) DO UPDATE SET
                        watermark_utc=excluded.watermark_utc""", (source, value.isoformat()))
            self.conn.execute("INSERT INTO runs VALUES (?,?,?,?,?,?)",
                              (run_id, signature, source_run_id, trigger_mode, trigger_id,
                               json.dumps(summary, sort_keys=True, allow_nan=False)))
            self.conn.commit()
        except BaseException:
            self.conn.rollback()
            raise
