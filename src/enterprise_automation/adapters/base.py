"""Read-only contract for CP1 sources; external writes are out of scope."""
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class Page:
    records: tuple[dict[str, Any], ...]
    next_cursor: int | None


class ReadOnlySourceAdapter(Protocol):
    source_system: str
    source_type: str

    def list_page(self, *, cursor: int = 0, page_size: int = 2) -> Page: ...


def page_slice(records: list[dict], *, cursor: int, page_size: int) -> Page:
    if not isinstance(cursor, int) or isinstance(cursor, bool) or cursor < 0 or cursor > len(records):
        raise ValueError("Invalid cursor")
    if not isinstance(page_size, int) or isinstance(page_size, bool) or not 1 <= page_size <= 100:
        raise ValueError("page_size must be an integer from 1 to 100")
    end = min(len(records), cursor + page_size)
    return Page(tuple(records[cursor:end]), end if end < len(records) else None)
