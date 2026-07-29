"""Tests for Telegram command handlers."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from telegram.ext import ConversationHandler

from bot.bot import (
    CONFIRM,
    EPISODE,
    SEASON,
    TITLE,
    cancel_job_updates,
    check_document,
    configure_commands,
    confirm_request,
    format_progress_message,
    getanime,
    help_command,
    process_worker_events,
    receive_episode,
    receive_season,
    receive_title,
    start,
    status_command,
)


def set_callback(mock_update, data):
    query = MagicMock()
    query.data = data
    query.answer = AsyncMock()
    query.edit_message_text = AsyncMock()
    query.message.message_id = 555
    mock_update.callback_query = query
    mock_update.effective_message = query.message
    return query


@pytest.mark.asyncio
async def test_start(mock_update, mock_context):
    await start(mock_update, mock_context)
    reply = mock_update.message.reply_text.call_args
    assert "Welcome to Meido" in reply.args[0]
    callbacks = [
        button.callback_data
        for row in reply.kwargs["reply_markup"].inline_keyboard
        for button in row
    ]
    assert "menu:getanime" in callbacks
    assert "menu:status" in callbacks


@pytest.mark.asyncio
async def test_bot_command_menu_is_registered():
    application = MagicMock()
    application.bot.set_my_commands = AsyncMock()

    await configure_commands(application)

    commands = application.bot.set_my_commands.call_args.args[0]
    names = [command.command for command in commands]
    assert names == [
        "start",
        "anime",
        "getanime",
        "status",
        "help",
        "cancel",
    ]


@pytest.mark.asyncio
async def test_help(mock_update, mock_context):
    await help_command(mock_update, mock_context)
    assert "/getanime" in mock_update.message.reply_text.call_args.args[0]


@pytest.mark.asyncio
async def test_cached_episode_is_sent(
    mock_update,
    mock_context,
    mock_store,
    sample_anime_data,
):
    mock_store.get_episode.return_value = sample_anime_data

    await getanime(mock_update, mock_context)

    mock_context.bot.send_video.assert_awaited_once()
    mock_store.increment_episode_queries.assert_called_once_with(
        "death_note", 1, 3
    )
    mock_store.enqueue_episode.assert_not_called()


@pytest.mark.asyncio
async def test_cache_miss_is_queued(mock_update, mock_context, mock_store):
    mock_store.get_episode.return_value = None
    mock_store.enqueue_episode.return_value = ("abcdef123456", True)

    await getanime(mock_update, mock_context)

    mock_store.enqueue_episode.assert_called_once()
    message = mock_update.message.reply_text.call_args_list[-1].args[0]
    assert "Queued" in message
    assert "abcdef12" in message
    mock_store.set_progress_message.assert_called_once_with(
        "abcdef123456",
        987654321,
        555,
    )


@pytest.mark.asyncio
async def test_duplicate_job_adds_waiter(mock_update, mock_context, mock_store):
    mock_store.get_episode.return_value = None
    mock_store.enqueue_episode.return_value = ("abcdef123456", False)

    await getanime(mock_update, mock_context)

    message = mock_update.message.reply_text.call_args_list[-1].args[0]
    assert "Already in progress" in message


@pytest.mark.asyncio
async def test_invalid_request_never_queues(mock_update, mock_context, mock_store):
    mock_update.message.text = "/getanime Death Note, 1"

    await getanime(mock_update, mock_context)

    mock_store.enqueue_episode.assert_not_called()
    assert "Episode" in mock_update.message.reply_text.call_args.args[0]


@pytest.mark.asyncio
async def test_guided_request_uses_buttons_and_confirmation(
    mock_update,
    mock_context,
    mock_store,
):
    mock_update.message.text = "/getanime"
    assert await getanime(mock_update, mock_context) == TITLE

    mock_update.message.text = "Fairy Tail"
    mock_update.effective_message = mock_update.message
    assert await receive_title(mock_update, mock_context) == SEASON

    season_query = set_callback(mock_update, "season:1")
    assert await receive_season(mock_update, mock_context) == EPISODE
    season_query.edit_message_text.assert_awaited_once()

    episode_query = set_callback(mock_update, "episode:2")
    assert await receive_episode(mock_update, mock_context) == CONFIRM
    assert "Episode 2" in episode_query.edit_message_text.call_args.kwargs["text"]

    mock_store.get_episode.return_value = None
    mock_store.enqueue_episode.return_value = ("a" * 32, True)
    confirm_query = set_callback(mock_update, "request:confirm")

    result = await confirm_request(mock_update, mock_context)

    assert result == ConversationHandler.END
    mock_store.enqueue_episode.assert_called_once_with(
        series_key="fairy_tail",
        series_name="Fairy Tail",
        season_id=1,
        episode_id=2,
        chat_id=987654321,
    )
    assert "Queued" in confirm_query.edit_message_text.call_args.kwargs["text"]


@pytest.mark.asyncio
async def test_status_lists_active_jobs_with_stop_button(
    mock_update,
    mock_context,
    mock_store,
):
    mock_store.get_active_jobs.return_value = [
        {
            "job_id": "a" * 32,
            "series_name": "Fairy Tail",
            "season_id": 1,
            "episode_id": 2,
            "status": "downloading",
            "phase": "downloading",
            "progress_percent": "45",
        }
    ]

    await status_command(mock_update, mock_context)

    reply = mock_update.message.reply_text.call_args
    assert "Active requests" in reply.args[0]
    assert "45%" in reply.args[0]
    callbacks = [
        button.callback_data
        for row in reply.kwargs["reply_markup"].inline_keyboard
        for button in row
    ]
    assert f"job:cancel:{'a' * 32}" in callbacks


@pytest.mark.asyncio
async def test_stop_updates_removes_only_current_waiter(
    mock_update,
    mock_context,
    mock_store,
):
    mock_store.remove_waiter.return_value = True
    query = set_callback(mock_update, f"job:cancel:{'a' * 32}")

    await cancel_job_updates(mock_update, mock_context)

    mock_store.remove_waiter.assert_called_once_with(
        "a" * 32,
        987654321,
    )
    mock_store.remove_progress_message.assert_called_once_with(
        "a" * 32,
        987654321,
    )
    assert "Updates stopped" in query.edit_message_text.call_args.kwargs["text"]


@pytest.mark.asyncio
async def test_uploaded_video_completes_job(
    mock_update,
    mock_context,
    mock_store,
):
    mock_update.message.video.file_id = "telegram-file-id"
    mock_update.message.caption = "meido:job123"
    mock_store.complete_job.return_value = [111, 222]

    await check_document(mock_update, mock_context)

    mock_store.complete_job.assert_called_once_with(
        "job123", "telegram-file-id"
    )
    assert mock_context.bot.send_video.await_count == 2


@pytest.mark.asyncio
async def test_upload_from_wrong_user_is_ignored(
    mock_update,
    mock_context,
    mock_store,
):
    mock_update.message.from_user.id = 999

    await check_document(mock_update, mock_context)

    mock_store.complete_job.assert_not_called()


@pytest.mark.asyncio
async def test_uploaded_video_document_completes_job(
    mock_update,
    mock_context,
    mock_store,
):
    mock_update.message.video = None
    mock_update.message.document.mime_type = "video/mp4"
    mock_update.message.document.file_id = "document-file-id"
    mock_update.message.caption = "meido:job123"
    mock_store.complete_job.return_value = [111]

    await check_document(mock_update, mock_context)

    mock_store.complete_job.assert_called_once_with(
        "job123",
        "document-file-id",
    )


@pytest.mark.asyncio
async def test_failure_event_notifies_waiters(
    mock_context,
    mock_store,
):
    mock_store.read_events.return_value = [
        ("1-0", {"event": "job_failed", "job_id": "job123"})
    ]
    mock_store.get_job.return_value = {"error": "Provider unavailable"}
    mock_store.take_failed_waiters.return_value = [111, 222]

    await process_worker_events(mock_context)

    assert mock_context.bot.send_message.await_count == 2
    markup = mock_context.bot.send_message.call_args.kwargs["reply_markup"]
    callbacks = [
        button.callback_data
        for row in markup.inline_keyboard
        for button in row
    ]
    assert "job:retry:job123" in callbacks
    mock_store.acknowledge_event.assert_called_once_with("1-0")


@pytest.mark.asyncio
async def test_progress_event_edits_the_queue_message(
    mock_context,
    mock_store,
):
    mock_store.read_events.return_value = [
        (
            "2-0",
            {
                "event": "job_progress",
                "job_id": "job123",
                "phase": "downloading",
                "percent": "45",
                "detail": "Segment 45/100",
                "backend": "animeparadise",
            },
        )
    ]
    mock_store.get_job.return_value = {
        "job_id": "job123",
        "series_name": "Death Note",
        "season_id": 1,
        "episode_id": 3,
    }
    mock_store.get_progress_messages.return_value = {111: 555}

    await process_worker_events(mock_context)

    edit = mock_context.bot.edit_message_text
    edit.assert_awaited_once()
    text = edit.call_args.kwargs["text"]
    assert "Downloading" in text
    assert "45%" in text
    assert "animeparadise" in text


def test_progress_message_has_bounded_bar():
    text = format_progress_message(
        {
            "job_id": "job123",
            "series_name": "Death Note",
            "season_id": 1,
            "episode_id": 3,
        },
        {
            "phase": "downloading",
            "percent": "250",
            "detail": "Segment 10/10",
        },
    )

    assert "100%" in text
    assert "[██████████]" in text
