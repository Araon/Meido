"""Tests for Telegram command handlers."""

from unittest.mock import MagicMock

import pytest

from bot.bot import (
    check_document,
    format_progress_message,
    getanime,
    help_command,
    process_worker_events,
    start,
)


@pytest.mark.asyncio
async def test_start(mock_update, mock_context):
    await start(mock_update, mock_context)
    assert "Thanks for using" in mock_update.message.reply_text.call_args.args[0]


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
    assert "already being prepared" in message


@pytest.mark.asyncio
async def test_invalid_request_never_queues(mock_update, mock_context, mock_store):
    mock_update.message.text = "/getanime Death Note, 1"

    await getanime(mock_update, mock_context)

    mock_store.enqueue_episode.assert_not_called()
    assert "Episode" in mock_update.message.reply_text.call_args.args[0]


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
