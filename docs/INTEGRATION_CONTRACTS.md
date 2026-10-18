# CP1 Synthetic Source Integration Contracts

All sources are fabricated portfolio fixtures. **No live ERP, CRM, ticketing, employer, customer or cloud system is connected.**

| Source | CP1 adapter | Entity | Stable key | Contract version | Endpoint / fixture |
|---|---|---|---|---|---|
| ERP | Simulated paged API | Orders | `order_id` | `erp.orders.v1` | `/erp/orders` / `data/fixtures/erp_orders.json` |
| CRM | Simulated paged API | Customers | `customer_id` | `crm.customers.v1` | `/crm/customers` / `data/fixtures/crm_customers.json` |
| TICKETING | CSV file drop | Tickets | `ticket_id` | `ticketing.tickets.v1` | `data/fixtures/ticketing_tickets.csv` |

Expected fields:
- **ERP**: `order_id` (string), `customer_id` (string), `amount_usd` (finite nonnegative numeric), `updated_at_utc` (ISO 8601 with timezone).
- **CRM**: `customer_id` (string), `customer_name` (string), `updated_at_utc` (ISO 8601 with timezone).
- **TICKETING**: `ticket_id` (string), `customer_id` (string), `priority` (string), `updated_at_utc` (ISO 8601 with timezone).

The CP1 contract rejects missing/blank required fields, unexpected attributes, malformed timestamps, invalid numeric values, and duplicate source keys. It validates each source independently; **cross-source entity joins and referential reconciliation are CP2**. It does not prove a business identity match or validate actual enterprise API responses.

Mock endpoints are deliberately on a separate `FastAPI` instance in `enterprise_automation.api.mock_systems`. Start locally only when desired with `uvicorn enterprise_automation.api.mock_systems:app --host 127.0.0.1 --port 9001` after setting `PYTHONPATH=src`. The mock endpoints are **not authenticated** and must **never be internet-exposed**. Adapters used in the CP1 ingestion demo read local mock fixtures directly; HTTP requests are tested with an in-process test client.

Mock pagination uses integer offset cursor (start at 0), a page size from 1 to 100, and `next_cursor=null` at completion. No network retry, rate limiting, real OAuth, or provider credentials are implemented in CP1. Those belong to later checkpoints.
