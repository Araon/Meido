"""Integration-level tests for the background worker workflow."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from downloaderService.contracts import AdapterError, DownloadFailed
from worker.main import ProgressReporter, process_job
from worker.upload_main import process_upload_job


def settings(tmp_path):
    return SimpleNamespace(
        download_root=tmp_path,
        downloader_max_job_attempts=3,
        downloader_retry_delay_seconds=60,
        upload_max_job_attempts=3,
        upload_retry_delay_seconds=60,
    )


def job():
    return {
        "job_id": "job123",
        "series_key": "death_note",
        "series_name": "Death Note",
        "season_id": 1,
        "episode_id": 3,
        "attempts": "0",
    }


def test_worker_downloads_and_queues_upload(tmp_path):
    store = MagicMock()
    store.get_job.return_value = job()
    downloader = MagicMock()
    media_file = tmp_path / "episode.mp4"
    media_file.write_bytes(b"video")
    downloader.download.return_value = media_file

    process_job(store, settings(tmp_path), downloader, "job123")

    downloader.download.assert_called_once()
    assert media_file.exists()
    store.enqueue_upload.assert_called_once_with("job123")
    store.update_job.assert_any_call(
        "job123",
        "downloaded",
        media_path=str(media_file.resolve()),
    )


@pytest.mark.asyncio
async def test_uploader_sends_and_waits_for_bot_confirmation(tmp_path):
    store = MagicMock()
    upload_job = job()
    media_file = tmp_path / "episode.mp4"
    media_file.write_bytes(b"video")
    upload_job["media_path"] = str(media_file)
    store.get_job.return_value = upload_job

    with patch(
        "worker.upload_main.upload_video_with_client",
        new=AsyncMock(return_value=SimpleNamespace(id=77)),
    ) as upload:
        await process_upload_job(
            store,
            settings(tmp_path),
            MagicMock(),
            MagicMock(),
            "job123",
        )

    upload.assert_awaited_once()
    store.update_job.assert_any_call(
        "job123",
        "awaiting_bot",
        telegram_message_id=77,
    )
    assert not media_file.exists()


@pytest.mark.asyncio
async def test_uploader_schedules_retry(tmp_path):
    store = MagicMock()
    upload_job = job()
    media_file = tmp_path / "episode.mp4"
    media_file.write_bytes(b"video")
    upload_job["media_path"] = str(media_file)
    store.get_job.return_value = upload_job

    with patch(
        "worker.upload_main.upload_video_with_client",
        new=AsyncMock(side_effect=ConnectionError("offline")),
    ), patch("worker.upload_main.time.time", return_value=1_000):
        await process_upload_job(
            store,
            settings(tmp_path),
            MagicMock(),
            MagicMock(),
            "job123",
        )

    store.schedule_upload_retry.assert_called_once()
    assert store.schedule_upload_retry.call_args.args[2] == 1_060
    assert media_file.exists()


def test_worker_schedules_transient_failure_without_immediate_retry(tmp_path):
    store = MagicMock()
    store.get_job.return_value = job()
    downloader = MagicMock()
    downloader.download.side_effect = DownloadFailed(
        [
            (
                "animeparadise",
                AdapterError(
                    "temporary",
                    "provider unavailable",
                    retryable=True,
                    retry_after=300,
                ),
            )
        ]
    )

    with patch("worker.main.time.time", return_value=1_000):
        process_job(store, settings(tmp_path), downloader, "job123")

    store.schedule_retry.assert_called_once()
    assert store.schedule_retry.call_args.args[2] == 1_300
    store.fail_job.assert_not_called()


def test_worker_fails_non_retryable_download(tmp_path):
    store = MagicMock()
    store.get_job.return_value = job()
    downloader = MagicMock()
    downloader.download.side_effect = DownloadFailed(
        [
            (
                "animeparadise",
                AdapterError("not_found", "episode unavailable"),
            )
        ]
    )

    process_job(store, settings(tmp_path), downloader, "job123")

    store.fail_job.assert_called_once()
    store.schedule_retry.assert_not_called()


def test_progress_reporter_throttles_small_same_phase_updates():
    store = MagicMock()
    clock = [100.0]
    reporter = ProgressReporter(store, "job123", clock=lambda: clock[0])

    reporter({"phase": "downloading", "percent": 10})
    reporter({"phase": "downloading", "percent": 12})
    reporter({"phase": "downloading", "percent": 15})
    reporter({"phase": "uploading", "percent": 0})

    assert store.publish_progress.call_count == 3
    assert store.publish_progress.call_args_list[0].kwargs["percent"] == 10
    assert store.publish_progress.call_args_list[1].kwargs["percent"] == 15
    assert store.publish_progress.call_args_list[2].kwargs["phase"] == "uploading"
