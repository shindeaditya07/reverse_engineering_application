class IngestError(Exception):
    """A source was rejected. `code` is stable for tests and logs; the message holds no secrets."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
