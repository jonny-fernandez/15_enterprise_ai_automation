def retryable_status(status_code: int) -> bool:
    return status_code in {408, 429, 500, 502, 503, 504}
