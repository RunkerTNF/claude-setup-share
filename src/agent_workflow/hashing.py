from __future__ import annotations

import hashlib
from pathlib import Path


_READ_CHUNK_SIZE = 1024 * 1024


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_runtime_normalized(
    data: bytes,
    *,
    home: Path | None = None,
    project: Path | None = None,
) -> str:
    """Hash generated content after replacing concrete runtime roots."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return sha256_bytes(data)
    replacements: list[tuple[str, str]] = []
    for root, placeholder in (
        (home, "{{HOME}}"),
        (project, "{{PROJECT}}"),
    ):
        if root is None:
            continue
        replacements.extend(
            (
                (str(root), placeholder),
                (root.as_posix(), placeholder),
            )
        )
    for source, placeholder in sorted(
        set(replacements),
        key=lambda item: len(item[0]),
        reverse=True,
    ):
        text = text.replace(source, placeholder)
    return sha256_bytes(text.encode("utf-8"))


def sha256_file(path: Path) -> str | None:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as file:
            for chunk in iter(lambda: file.read(_READ_CHUNK_SIZE), b""):
                digest.update(chunk)
    except FileNotFoundError:
        return None
    return digest.hexdigest()
