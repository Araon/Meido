"""Tests for Telegram command parsing."""

import pytest

from bot.commands import (
    normalize_series_name,
    parse_search_query,
    showhelp,
    validate_search_query,
)


def test_help_contains_getanime_usage():
    result = showhelp()

    assert "/getanime" in result
    assert "<name>, <season>, <episode>" in result


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (
            "Death Note, 1, 3",
            {
                "series_name": "Death Note",
                "season_id": 1,
                "episode_id": 3,
            },
        ),
        (
            "  Death Note  , season 1, episode 3 ",
            {
                "series_name": "Death Note",
                "season_id": 1,
                "episode_id": 3,
            },
        ),
        (
            "Death Note, 1",
            {
                "series_name": "Death Note",
                "season_id": 1,
                "episode_id": -1,
            },
        ),
        (
            "",
            {
                "series_name": "",
                "season_id": -1,
                "episode_id": -1,
            },
        ),
    ],
)
def test_parse_search_query(raw, expected):
    assert parse_search_query(raw) == expected


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Death Note", "death_note"),
        ("DEATH  NOTE", "death_note"),
        ("Death Note: The Series!", "death_note_the_series"),
        ("", ""),
        ("   ", ""),
    ],
)
def test_normalize_series_name(title, expected):
    assert normalize_series_name(title) == expected


@pytest.mark.parametrize(
    ("query", "message"),
    [
        ({"series_name": "", "season_id": 1, "episode_id": 1}, "name"),
        (
            {"series_name": "Death Note", "season_id": -1, "episode_id": 1},
            "Season",
        ),
        (
            {"series_name": "Death Note", "season_id": 1, "episode_id": 0},
            "Episode",
        ),
    ],
)
def test_invalid_query(query, message):
    assert message in validate_search_query(query)


def test_valid_query():
    assert (
        validate_search_query(
            {"series_name": "Death Note", "season_id": 1, "episode_id": 3}
        )
        is None
    )
