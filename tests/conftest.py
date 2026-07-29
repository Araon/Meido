"""Shared pytest fixtures."""

import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest


os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")
os.environ.setdefault("TELEGRAM_AGENT_USER_ID", "123456789")


@pytest.fixture
def mock_update():
    update = MagicMock()
    update.message.from_user.id = 123456789
    update.message.text = "/getanime Death Note, 1, 3"
    update.message.reply_text = AsyncMock()
    update.message.reply_text.return_value.message_id = 555
    update.callback_query = None
    update.effective_message = update.message
    update.effective_chat.id = 987654321
    return update


@pytest.fixture
def mock_context():
    context = MagicMock()
    context.bot.send_video = AsyncMock()
    context.bot.send_message = AsyncMock()
    context.bot.edit_message_text = AsyncMock()
    context.user_data = {}
    return context


@pytest.fixture
def mock_store(monkeypatch):
    import bot.bot

    store = MagicMock()
    store.get_progress_messages.return_value = {}
    monkeypatch.setattr(bot.bot, "STORE", store)
    monkeypatch.setattr(
        bot.bot,
        "SETTINGS",
        SimpleNamespace(agent_user_id=123456789),
    )
    return store


@pytest.fixture
def sample_anime_data():
    return {
        "series_key": "death_note",
        "series_name": "Death Note",
        "season_id": 1,
        "episode_id": 3,
        "file_id": "telegram-file-id",
        "times_queried": 5,
    }
