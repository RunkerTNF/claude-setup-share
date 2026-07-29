from __future__ import annotations

import os
from pathlib import Path
import secrets
from typing import TextIO

from agent_workflow.errors import TransactionBusyError, UnsafePathError


class ScopeLock:
    """A lock file which never follows or replaces an existing path."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._held = False
        self._identity: tuple[int, int] | None = None
        self._token = secrets.token_hex(32)
        self._handle: TextIO | None = None

    def __enter__(self) -> "ScopeLock":
        if self.path.is_symlink():
            raise UnsafePathError(f"scope lock is a symlink: {self.path}")
        lock_file: TextIO | None = None
        try:
            lock_file = self.path.open("x+", encoding="utf-8")
            self._handle = lock_file
            opened_stat = self.path.lstat()
            self._identity = (opened_stat.st_dev, opened_stat.st_ino)
            self._write_token(lock_file)
            self._flush_token(lock_file)
            os.fsync(lock_file.fileno())
            stat = os.fstat(lock_file.fileno())
            self._identity = (stat.st_dev, stat.st_ino)
            if os.name == "nt":
                # Windows cannot unlink an open pathname; retain the identity/token instead.
                lock_file.close()
                self._handle = None
        except FileExistsError as error:
            raise TransactionBusyError(f"transaction scope is locked: {self.path}") from error
        except Exception as error:
            self._cleanup_partial_acquisition(error)
            raise
        self._held = True
        return self

    def _write_token(self, lock_file: TextIO) -> None:
        lock_file.write(f"agent-workflow transaction lock {self._token}\n")

    def _flush_token(self, lock_file: TextIO) -> None:
        lock_file.flush()

    def _cleanup_partial_acquisition(self, original_error: Exception) -> None:
        try:
            if self._handle is not None:
                self._handle.close()
                self._handle = None
            stat = self.path.lstat()
            if self.path.is_symlink():
                return
            if self._identity is not None and self._identity != (stat.st_dev, stat.st_ino):
                return
            if self._identity is None and self.path.read_text(encoding="utf-8") != f"agent-workflow transaction lock {self._token}\n":
                return
            self.path.unlink()
        except FileNotFoundError:
            return
        except Exception as cleanup_error:
            original_error.add_note(f"partial scope lock cleanup failed: {cleanup_error}")

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
            if self.path.read_text(encoding="utf-8") != f"agent-workflow transaction lock {self._token}\n":
                return
            # Windows lacks unlink-by-handle; a final pathname swap remains possible after this check.
            if self._handle is not None:
                self._handle.close()
                self._handle = None
            self.path.unlink()
        except Exception as error:
            if _value is not None:
                _value.add_note(f"scope lock cleanup failed: {error}")
                return
            raise
        finally:
            if self._handle is not None:
                self._handle.close()
                self._handle = None
            self._held = False
