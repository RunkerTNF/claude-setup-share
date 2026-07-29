from __future__ import annotations

import os
from pathlib import Path
import secrets

from agent_workflow.errors import TransactionBusyError, UnsafePathError


class ScopeLock:
    """A lock file which never follows or replaces an existing path."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._held = False
        self._identity: tuple[int, int] | None = None
        self._token = secrets.token_hex(32)

    def __enter__(self) -> "ScopeLock":
        if self.path.is_symlink():
            raise UnsafePathError(f"scope lock is a symlink: {self.path}")
        try:
            with self.path.open("x", encoding="utf-8") as lock_file:
                lock_file.write(f"agent-workflow transaction lock {self._token}\n")
                lock_file.flush()
                stat = os.fstat(lock_file.fileno())
                self._identity = (stat.st_dev, stat.st_ino)
        except FileExistsError as error:
            raise TransactionBusyError(f"transaction scope is locked: {self.path}") from error
        self._held = True
        return self

    def __exit__(self, _type: object, _value: object, _traceback: object) -> None:
        if not self._held:
            return
        try:
            try:
                stat = self.path.lstat()
            except FileNotFoundError:
                return
            if self.path.is_symlink() or self._identity != (stat.st_dev, stat.st_ino):
                return
            self.path.unlink()
        finally:
            self._held = False
