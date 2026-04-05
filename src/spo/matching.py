"""Normalization and fuzzy matching helpers for cross-service catalog items."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any, cast

from spo.models import CanonicalWork, CollectionKind, Service
from spo.utils import stable_hash

FEAT_PATTERN = re.compile(r"\b(feat|ft|featuring)\.?\b", re.IGNORECASE)
PUNCT_PATTERN = re.compile(r"[^\w\s]")
SPACE_PATTERN = re.compile(r"\s+")
SECONDS_DURATION_CUTOFF = 10_000
YEAR_PREFIX_LENGTH = 4
EXACT_DURATION_DELTA_MS = 2_000
CLOSE_DURATION_DELTA_MS = 8_000
MATCH_ACCEPT_SCORE = 0.80
MATCH_ACCEPT_WITH_GAP_SCORE = 0.65
MATCH_ACCEPT_MIN_GAP = 0.10


@dataclass(slots=True)
class MatchResult:
    """The outcome of matching one source item against target candidates."""

    candidate: dict[str, Any] | None
    score: float
    gap: float
    accepted: bool
    method: str


def normalize_text(value: str | None) -> str:
    """Normalize text for fuzzy comparisons across service payloads."""
    if not value:
        return ""
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    normalized = FEAT_PATTERN.sub("", normalized.lower().replace("&", " and "))
    normalized = PUNCT_PATTERN.sub(" ", normalized)
    return SPACE_PATTERN.sub(" ", normalized).strip()


def _parse_duration_ms(value: object) -> int | None:
    duration_ms: int | None = None
    if value is None:
        return duration_ms
    if isinstance(value, int):
        duration_ms = value if value > SECONDS_DURATION_CUTOFF else value * 1000
    elif isinstance(value, float):
        duration_ms = int(value * 1000)
    elif isinstance(value, str):
        if value.isdigit():
            duration_ms = int(value)
        else:
            parts = [int(part) for part in value.split(":") if part.isdigit()]
            if parts:
                total_seconds = 0
                for part in parts:
                    total_seconds = total_seconds * 60 + part
                duration_ms = total_seconds * 1000
    return duration_ms


def _coerce_artist_name(value: object) -> str | None:
    """Return a normalized artist name string if one can be derived from a raw item."""
    candidate = cast("Mapping[str, object]", value).get("name") if isinstance(value, Mapping) else value

    if not candidate:
        return None
    return str(candidate)


def _extract_artists(raw: dict[str, Any]) -> list[str]:
    artists_payload = raw.get("artists")
    if isinstance(artists_payload, list):
        artists = [
            artist_name
            for item in artists_payload
            if (artist_name := _coerce_artist_name(item)) is not None
        ]
        if artists:
            return artists

    for key in ("artist", "author", "owner"):
        value = raw.get(key)
        if value:
            return [str(value)]

    return []


def _extract_container_title(raw: dict[str, Any]) -> str | None:
    album = raw.get("album")
    if isinstance(album, dict):
        return album.get("name") or album.get("title")
    if isinstance(album, str):
        return album
    for key in ("show", "podcast", "container_title", "description"):
        value = raw.get(key)
        if isinstance(value, dict):
            return value.get("name") or value.get("title")
        if value:
            return str(value)
    return None


def _extract_year(raw: dict[str, Any]) -> int | None:
    for key in ("year", "release_year"):
        value = raw.get(key)
        if isinstance(value, int):
            return value
    for key in ("release_date", "published", "publishedAt"):
        value = raw.get(key)
        if isinstance(value, str) and len(value) >= YEAR_PREFIX_LENGTH:
            year_prefix = value[:YEAR_PREFIX_LENGTH]
            if year_prefix.isdigit():
                return int(year_prefix)
    return None


def _extract_external_ids(raw: dict[str, Any]) -> dict[str, str]:
    external_ids = raw.get("external_ids")
    if isinstance(external_ids, dict):
        return {str(key): str(value) for key, value in external_ids.items() if value}
    result: dict[str, str] = {}
    for key in ("isrc", "upc"):
        if raw.get(key):
            result[key] = str(raw[key])
    return result


def canonicalize(service: Service, kind: CollectionKind, source_id: str, raw: dict[str, Any]) -> CanonicalWork:
    """Build a canonical representation of a service payload."""
    title = raw.get("title") or raw.get("name") or raw.get("series") or raw.get("channel") or ""
    primary_creators = _extract_artists(raw)
    container_title = _extract_container_title(raw)
    work = CanonicalWork(
        kind=kind,
        source_service=service,
        source_id=source_id,
        title=str(title),
        primary_creators=primary_creators,
        secondary_creators=[],
        container_title=container_title,
        duration_ms=_parse_duration_ms(raw.get("duration_ms") or raw.get("duration") or raw.get("length")),
        year=_extract_year(raw),
        explicit=raw.get("explicit"),
        external_ids=_extract_external_ids(raw),
    )
    fingerprint_seed = "|".join(
        [
            kind.value,
            normalize_text(work.title),
            ",".join(sorted(normalize_text(value) for value in work.primary_creators)),
            normalize_text(work.container_title),
        ],
    )
    work.fingerprint = stable_hash(fingerprint_seed)
    return work


def work_similarity(left: CanonicalWork, right: CanonicalWork) -> float:
    """Score how closely two canonical works represent the same media."""
    if left.external_ids and right.external_ids:
        shared_keys = set(left.external_ids).intersection(right.external_ids)
        for key in shared_keys:
            if left.external_ids[key] == right.external_ids[key]:
                return 1.0

    title_score = SequenceMatcher(None, normalize_text(left.title), normalize_text(right.title)).ratio()
    creator_score = SequenceMatcher(
        None,
        " ".join(sorted(normalize_text(value) for value in left.primary_creators)),
        " ".join(sorted(normalize_text(value) for value in right.primary_creators)),
    ).ratio()
    container_score = SequenceMatcher(
        None,
        normalize_text(left.container_title),
        normalize_text(right.container_title),
    ).ratio()

    duration_score = 0.0
    if left.duration_ms and right.duration_ms:
        delta = abs(left.duration_ms - right.duration_ms)
        duration_score = 1.0 if delta <= EXACT_DURATION_DELTA_MS else 0.5 if delta <= CLOSE_DURATION_DELTA_MS else 0.0

    year_score = 0.0
    if left.year and right.year:
        year_score = 1.0 if left.year == right.year else 0.0

    explicit_score = 0.0
    if left.explicit is not None and right.explicit is not None:
        explicit_score = 1.0 if left.explicit == right.explicit else 0.0

    return round(
        (title_score * 0.45)
        + (creator_score * 0.25)
        + (container_score * 0.15)
        + (duration_score * 0.10)
        + (year_score * 0.03)
        + (explicit_score * 0.02),
        4,
    )


def choose_best_match(source: CanonicalWork, candidates: list[dict[str, Any]], target_service: Service) -> MatchResult:
    """Select the best acceptable candidate for a source work."""
    if not candidates:
        return MatchResult(
            candidate=None,
            score=0.0,
            gap=0.0,
            accepted=False,
            method="no_candidates",
        )

    scored: list[tuple[float, dict[str, Any], CanonicalWork]] = []
    for candidate in candidates:
        candidate_id = str(
            candidate.get("id")
            or candidate.get("videoId")
            or candidate.get("playlistId")
            or candidate.get("browseId")
            or candidate.get("channelId")
            or "",
        )
        if not candidate_id:
            continue
        candidate_work = canonicalize(target_service, source.kind, candidate_id, candidate)
        scored.append((work_similarity(source, candidate_work), candidate, candidate_work))

    if not scored:
        return MatchResult(
            candidate=None,
            score=0.0,
            gap=0.0,
            accepted=False,
            method="invalid_candidates",
        )

    scored.sort(key=lambda item: item[0], reverse=True)
    best_score, best_candidate, _ = scored[0]
    second_score = scored[1][0] if len(scored) > 1 else 0.0
    accepted = best_score >= MATCH_ACCEPT_SCORE or (
        best_score >= MATCH_ACCEPT_WITH_GAP_SCORE and best_score - second_score >= MATCH_ACCEPT_MIN_GAP
    )
    return MatchResult(
        candidate=best_candidate,
        score=best_score,
        gap=round(best_score - second_score, 4),
        accepted=accepted,
        method="external_id" if best_score == 1.0 else "fuzzy",
    )


def playlist_name_match_score(source_name: str, target_name: str) -> float:
    """Score how closely two playlist names match after normalization."""
    left = normalize_text(source_name)
    right = normalize_text(target_name)
    if left == right:
        return 1.0
    return SequenceMatcher(None, left, right).ratio()
