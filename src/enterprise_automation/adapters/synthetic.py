"""Offline synthetic sources: simulated paginated ERP/CRM APIs and CSV drop."""
import csv
import json
from pathlib import Path

from enterprise_automation.adapters.base import Page, page_slice


class SyntheticAPIAdapter:
    source_type = "simulated_api"

    def __init__(self, source_system: str, fixture_path: Path):
        if source_system not in {"ERP", "CRM"}:
            raise ValueError("Only ERP and CRM are supported by this CP1 mock")
        self.source_system = source_system
        contents = json.loads(Path(fixture_path).read_text(encoding="utf-8"))
        if not isinstance(contents, list) or any(not isinstance(row, dict) for row in contents):
            raise ValueError("Mock API fixture must be a list of objects")
        self._records = contents

    def list_page(self, *, cursor: int = 0, page_size: int = 2) -> Page:
        return page_slice(self._records, cursor=cursor, page_size=page_size)


class CSVFileAdapter:
    source_type = "csv_file_drop"
    source_system = "TICKETING"

    def __init__(self, fixture_path: Path):
        with Path(fixture_path).open("r", encoding="utf-8-sig", newline="") as handle:
            self._records = list(csv.DictReader(handle))

    def list_page(self, *, cursor: int = 0, page_size: int = 2) -> Page:
        return page_slice(self._records, cursor=cursor, page_size=page_size)


def build_demo_sources(fixtures_dir: Path):
    fixtures_dir = Path(fixtures_dir)
    return (
        SyntheticAPIAdapter("ERP", fixtures_dir / "erp_orders.json"),
        SyntheticAPIAdapter("CRM", fixtures_dir / "crm_customers.json"),
        CSVFileAdapter(fixtures_dir / "ticketing_tickets.csv"),
    )
