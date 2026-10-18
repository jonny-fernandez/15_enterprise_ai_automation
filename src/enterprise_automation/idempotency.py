"""In-memory CP1 idempotency: durable persistence is scheduled for CP2."""


class IdempotencyStore:
    def __init__(self) -> None:
        self._processed: dict[str, str] = {}

    def seen(self, key: str) -> bool:
        return key in self._processed

    def fingerprint(self, key: str) -> str | None:
        return self._processed.get(key)

    def mark(self, key: str, fingerprint: str = "") -> None:
        existing = self.fingerprint(key)
        if existing is not None and existing != fingerprint:
            raise ValueError("Idempotency conflict")
        self._processed[key] = fingerprint
