from typing import Protocol

class Warehouse(Protocol):
    def load_rows(self, table: str, rows: list[dict]) -> int: ...
