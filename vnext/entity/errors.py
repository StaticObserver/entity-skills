class EntityError(Exception):
    """A user-facing, deterministic workspace error."""

    def __init__(self, message: str, *, code: str = "error") -> None:
        super().__init__(message)
        self.code = code
