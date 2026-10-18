"""Bounded deterministic retry schedule for *idempotent synthetic operations only*."""
from dataclasses import dataclass


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3
    timeout_ticks: int = 8
    base_backoff_ticks: int = 2

    def __post_init__(self):
        if (type(self.max_attempts) is not int or not 1 <= self.max_attempts <= 5 or
            type(self.timeout_ticks) is not int or not 1 <= self.timeout_ticks <= 100 or
            type(self.base_backoff_ticks) is not int or not 1 <= self.base_backoff_ticks <= 30):
            raise ValueError("Unsafe retry budget")

    def next_tick(self, tick: int, attempt: int) -> int:
        return tick + min(self.base_backoff_ticks * (2 ** (attempt - 1)), 60)


class SyntheticTransientFailure(Exception):
    pass


class SyntheticPermanentFailure(Exception):
    pass
