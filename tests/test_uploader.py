"""Tests for Telegram upload destination safety."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from uploaderService.main import bot_id_from_token, resolve_bot_recipient


@pytest.mark.asyncio
async def test_bot_recipient_is_accepted():
    client = MagicMock()
    bot = SimpleNamespace(
        bot=True,
        id=5087415335,
        username="anime_araon_bot",
    )
    client.get_entity = AsyncMock(return_value=bot)

    result = await resolve_bot_recipient(
        client,
        "@anime_araon_bot",
        5087415335,
    )

    assert result is bot


@pytest.mark.asyncio
async def test_user_recipient_is_rejected():
    client = MagicMock()
    user = SimpleNamespace(bot=False, id=993284683, username="realAra0n")
    client.get_entity = AsyncMock(return_value=user)

    with pytest.raises(ValueError, match="must identify a bot account"):
        await resolve_bot_recipient(client, "@realAra0n")


@pytest.mark.asyncio
async def test_different_bot_is_rejected():
    client = MagicMock()
    other_bot = SimpleNamespace(
        bot=True,
        id=123,
        username="different_bot",
    )
    client.get_entity = AsyncMock(return_value=other_bot)

    with pytest.raises(ValueError, match="does not match"):
        await resolve_bot_recipient(
            client,
            "@different_bot",
            5087415335,
        )


def test_bot_id_is_derived_without_exposing_token():
    assert bot_id_from_token("5087415335:secret") == 5087415335
