"""Separate, synthetic-only HTTP mocks. Never point at a real service."""
from pathlib import Path
from fastapi import FastAPI, HTTPException, Query

from enterprise_automation.adapters.synthetic import SyntheticAPIAdapter

fixtures = Path(__file__).resolve().parents[3] / "data" / "fixtures"
app = FastAPI(title="Synthetic ERP and CRM APIs (OFFLINE DEMO)")


def _list(source: str, cursor: int, page_size: int):
    name = "erp_orders.json" if source == "ERP" else "crm_customers.json"
    adapter = SyntheticAPIAdapter(source, fixtures / name)
    try:
        page = adapter.list_page(cursor=cursor, page_size=page_size)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"records": page.records, "next_cursor": page.next_cursor, "source_system": source}


@app.get("/erp/orders")
def erp_orders(cursor: int = Query(default=0, ge=0), page_size: int = Query(default=2, ge=1, le=100)):
    return _list("ERP", cursor, page_size)


@app.get("/crm/customers")
def crm_customers(cursor: int = Query(default=0, ge=0), page_size: int = Query(default=2, ge=1, le=100)):
    return _list("CRM", cursor, page_size)
