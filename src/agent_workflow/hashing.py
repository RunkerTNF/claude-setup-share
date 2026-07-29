from __future__ import annotations

import hashlib
from pathlib import Path


_READ_CHUNK_SIZE = 1024 * 1024


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str | None:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as file:
            for chunk in iter(lambda: file.read(_READ_CHUNK_SIZE), b""):
                digest.update(chunk)
    except FileNotFoundError:
        return None
    return digest.hexdigest()
