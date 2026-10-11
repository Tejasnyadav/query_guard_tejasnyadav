from dataclasses import dataclass



 

@dataclass(slots=True)

class DatabaseOperationError(Exception):

    code: str

    message: str

    sqlstate: str | None = None

    retryable: bool = False


 

    def __str__(self) -> str:

        return self.message



 

class AuditStorageError(RuntimeError):

    """Raised when QueryGuard cannot write the mandatory audit record."""


 