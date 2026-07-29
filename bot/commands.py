"""Parsing and validation for Telegram bot commands."""

import re


def showhelp():
    return (
        "Available commands:\n"
        "/getanime <name>, <season>, <episode> - download an anime episode\n"
        "Example: /getanime Death Note, 1, 3"
    )


def normalize_series_name(series_name):
    """Create a lowercase Redis/filesystem-safe series key."""
    if not series_name:
        return ""
    normalized = series_name.lower().strip()
    return re.sub(r"[^a-z0-9]+", "_", normalized).strip("_")


def parse_search_query(raw_input):
    fields = raw_input.split(",")
    series_name = fields[0].strip() if fields else ""
    season_id = _parse_number(fields, 1)
    episode_id = _parse_number(fields, 2)
    return {
        "series_name": series_name,
        "season_id": season_id,
        "episode_id": episode_id,
    }


def _parse_number(fields, index):
    if len(fields) <= index:
        return -1
    digits = "".join(character for character in fields[index] if character.isdigit())
    return int(digits) if digits else -1


def validate_search_query(query):
    """Return a user-facing error for an invalid parsed query, or ``None``."""
    if not query.get("series_name") or not normalize_series_name(
        query["series_name"]
    ):
        return "Please provide an anime name."
    if query.get("season_id", -1) < 1:
        return "Season must be a positive whole number."
    if query.get("episode_id", -1) < 1:
        return "Episode must be a positive whole number."
    return None
