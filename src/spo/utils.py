"""Shared utility helpers used across the spo codebase."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from hashlib import sha1
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Sequence


def utcnow() -> str:
    """Return the current UTC timestamp as an ISO 8601 string."""
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def json_dumps(value: object) -> str:
    """Serialize a JSON value with stable key ordering."""
    return json.dumps(value, ensure_ascii=True, sort_keys=True)


def json_loads(value: str | bytes | None) -> object | None:
    """Deserialize a JSON string or return `None` for empty values."""
    if not value:
        return None
    return json.loads(value)


def chunked[T](values: Sequence[T] | Iterable[T], size: int) -> Iterator[list[T]]:
    """Yield consecutive batches from an iterable."""
    batch: list[T] = []
    for value in values:
        batch.append(value)
        if len(batch) == size:
            yield batch
            batch = []
    if batch:
        yield batch


def stable_hash(value: str) -> str:
    """Return a stable SHA-1 digest for the provided string."""
    return sha1(value.encode("utf-8"), usedforsecurity=False).hexdigest()
