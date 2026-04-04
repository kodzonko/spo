from __future__ import annotations

import json
from collections.abc import Iterable, Iterator, Sequence
from datetime import UTC, datetime
from hashlib import sha1
from typing import Any, TypeVar

T = TypeVar("T")


def utcnow() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True)


def json_loads(value: str | bytes | None) -> Any:
    if not value:
        return None
    return json.loads(value)


def chunked(values: Sequence[T] | Iterable[T], size: int) -> Iterator[list[T]]:
    batch: list[T] = []
    for value in values:
        batch.append(value)
        if len(batch) == size:
            yield batch
            batch = []
    if batch:
        yield batch


def stable_hash(value: str) -> str:
    return sha1(value.encode("utf-8")).hexdigest()
