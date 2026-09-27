"""Object storage abstraction for future audio/image assets.

Vercel's filesystem is read-only, so production must use a remote backend
(Vercel Blob, S3, R2...). Implement :class:`StorageBackend` for it and select
it in :func:`get_storage`.
"""
from __future__ import annotations

from pathlib import Path
from typing import Protocol


class StorageBackend(Protocol):
    def put(self, key: str, data: bytes, content_type: str) -> str:
        """Stores ``data`` and returns a public URL."""

    def delete(self, key: str) -> None: ...

    def url(self, key: str) -> str: ...


class LocalStorage:
    """Development-only backend writing under ``instance/media``."""

    def __init__(self, root: Path, base_url: str = "/media") -> None:
        self.root = root
        self.base_url = base_url.rstrip("/")

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if self.root.resolve() not in path.parents:
            raise ValueError("invalid storage key")
        return path

    def put(self, key: str, data: bytes, content_type: str) -> str:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return self.url(key)

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)

    def url(self, key: str) -> str:
        return f"{self.base_url}/{key}"


def get_storage(app) -> StorageBackend:
    return LocalStorage(Path(app.instance_path) / "media")
