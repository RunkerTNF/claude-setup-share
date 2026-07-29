from __future__ import annotations

from pathlib import Path

from agent_workflow.errors import TransactionBusyError, UnsafePathError


class ScopeLock:
    """A lock file which never follows or replaces an existing path."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._held = False

    def __enter__(self) -> "ScopeLock":
        if self.path.is_symlink():
            raise UnsafePathError(f"scope lock is a symlink: {self.path}")
        try:
            with self.path.open("x", encoding="utf-8") as lock_file:
                lock_file.write("agent-workflow transaction lock\n")
                lock_file.flush()
        except FileExistsError as error:
            raise TransactionBusyError(f"transaction scope is locked: {self.path}") from error
        self._held = True
        return self

    def __exit__(self, _type: object, _value: object, _traceback: object) -> None:
        if not self._held:
            return
        try:
            if self.path.is_symlink():
                raise UnsafePathError(f"scope lock changed into a symlink: {self.path}")
            self.path.unlink(missing_ok=True)
        finally:
            self._held = False
