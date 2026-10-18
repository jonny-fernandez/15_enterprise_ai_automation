# CP4 — Azure architecture decision and deployment boundary

**Decision (2026-10-18): Architecture mapping only, NOT a deployment.** The user approved documenting Azure integration without provisioning resources, incurring costs or performing external writes. A live deployment would require a separate explicit authorization and prerequisites.

## Architecture mapping from tested local code

| Tested local component | Possible Azure implementation | Not yet verified |
| --- | --- | --- |
| Synthetic ERP/CRM FastAPI + CSV adapter | Azure Functions (HTTP/Timer) or container app | Live credentials, external connectors |
| SQLite durable queue and DLQ | Azure Service Bus queues + DLQ | Broker receive/ack/redelivery, distributed ordering |
| Raw JSONL + processed Parquet | Azure Blob / ADLS Gen2 | Managed identities, access control, blob transactions |
| Python + local PySpark transforms | Databricks or Synapse serverless/managed Spark, only if justified | Distributed workers, scale, network security and cost |
| Local key injection | Key Vault + managed identity | Key rotation, RBAC and enterprise OAuth |
| Local manifests, hashes, metric snapshots | Application Insights / Azure Monitor | Live telemetry and alerting |

## Decision gate before any Azure deploy

1. Obtain explicit approval for the subscription/tenant, resource group, location, test budget and resource deletion policy.
2. Select smallest justified architecture; Service Bus / Functions / Blob can be explored independently of paid Databricks.
3. Identify data egress, credentials and permissions. Synthetic-only, no employer/customer data.
4. Run offline deployment/identity/IaC lint and security review before enabling cloud resource writes.
5. Record real deployment IDs, logs, costs and tests only if deployment happens. Do not present this document or CI as proof of deployment.

**Current evidence:** Local Python 3.12, Spark 4.0.4, Hadoop Windows native helper and SQLite; simulated sources. No live Azure subscription/service was used.
