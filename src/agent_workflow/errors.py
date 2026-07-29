class AgentWorkflowError(Exception):
    def __init__(self, message: str, exit_code: int = 2) -> None:
        super().__init__(message)
        self.exit_code = exit_code


class UnsafePathError(AgentWorkflowError):
    pass


class SchemaValidationError(AgentWorkflowError):
    pass


class SourceChangedError(AgentWorkflowError):
    pass


class BackupError(AgentWorkflowError):
    pass


class TransactionBusyError(AgentWorkflowError):
    pass
