"""Tests for matching and normalization helpers."""

from spo.matching import canonicalize, choose_best_match, normalize_text
from spo.models import CollectionKind, Service


def test_normalize_text_removes_feat_and_punctuation() -> None:
    """Test that normalization strips featuring markers and punctuation."""
    assert normalize_text("Song Title (feat. Artist B)!") == "song title artist b"


def test_choose_best_match_accepts_album_mismatch_when_title_and_artist_align() -> None:
    """Test that strong title and artist matches can tolerate album mismatches."""
    source = canonicalize(
        Service.SPOTIFY,
        CollectionKind.SAVED_TRACK,
        "src-1",
        {
            "id": "src-1",
            "name": "Best Song",
            "artists": [{"name": "Main Artist"}, {"name": "Guest Artist"}],
            "album": {"name": "Original Album"},
            "duration_ms": 210000,
        },
    )
    match = choose_best_match(
        source,
        [
            {
                "videoId": "yt-1",
                "title": "Best Song",
                "artists": [{"name": "Main Artist"}],
                "album": {"name": "Compilation"},
                "duration": "3:30",
            },
        ],
        Service.YTMUSIC,
    )
    assert match.accepted is True
    assert match.candidate is not None
