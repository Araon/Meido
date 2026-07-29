#!/usr/bin/env python3
"""Consume completed downloads and upload them through one Telegram session."""

import asyncio
import logging
import os
from pathlib import Path
import socket
import sys
import time

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bot.store import initialize_store
from meido_settings import load_settings
from uploaderService.main import (
    authorized_client,
    bot_id_from_token,
    resolve_bot_recipient,
    upload_video_with_client,
)
from worker.main import ProgressReporter, download_path


logger = logging.getLogger(__name__)


def media_path_for_job(settings, job):
    configured_path = job.get("media_path")
    if configured_path:
        return Path(configured_path)
    return download_path(settings, job) / "episode.mp4"


async def process_upload_job(
    store,
    settings,
    client,
    recipient,
    job_id,
):
    job = store.get_job(job_id)
    if not job:
        raise LookupError(f"Job not found: {job_id}")

    attempts = int(job.get("upload_attempts", 0)) + 1
    media_file = media_path_for_job(settings, job).resolve()
    reporter = ProgressReporter(store, job_id)
    store.update_job(
        job_id,
        "uploading",
        upload_attempts=attempts,
    )
    reporter(
        {
            "phase": "uploading",
            "percent": 0,
            "detail": "Starting Telegram upload",
        }
    )

    try:
        sent_message = await upload_video_with_client(
            client,
            recipient,
            media_file,
            job_id,
            progress_callback=reporter,
        )
        reporter(
            {
                "phase": "awaiting_bot",
                "percent": 100,
                "detail": "Uploaded; waiting for bot confirmation",
            }
        )
        store.update_job(
            job_id,
            "awaiting_bot",
            telegram_message_id=getattr(sent_message, "id", ""),
        )
        media_file.unlink(missing_ok=True)
    except Exception as error:
        if attempts < settings.upload_max_job_attempts:
            retry_at = int(
                time.time() + settings.upload_retry_delay_seconds
            )
            store.schedule_upload_retry(job_id, error, retry_at)
            logger.warning(
                "Upload %s failed on attempt %s/%s; retry scheduled: %s",
                job_id,
                attempts,
                settings.upload_max_job_attempts,
                error,
            )
        else:
            store.fail_job(job_id, error)
            logger.exception("Upload %s failed permanently", job_id)


async def process_upload_message(
    store,
    settings,
    client,
    recipient,
    message_id,
    job_id,
):
    try:
        await process_upload_job(
            store,
            settings,
            client,
            recipient,
            job_id,
        )
    except Exception:
        logger.exception("Could not process upload message for job %s", job_id)
    finally:
        await asyncio.to_thread(store.acknowledge_upload, message_id)


async def run():
    settings = load_settings(require_uploader=True)
    store = initialize_store(settings.redis_url)
    consumer_name = f"{socket.gethostname()}-{os.getpid()}"
    client = await authorized_client(settings)
    try:
        recipient = await resolve_bot_recipient(
            client,
            settings.bot_username,
            bot_id_from_token(settings.bot_token),
        )
        concurrency = settings.upload_concurrency
        pending = set()
        logger.info(
            "Uploader %s is ready with %s upload slots",
            consumer_name,
            concurrency,
        )

        while True:
            await asyncio.to_thread(store.promote_due_upload_retries)
            completed = {task for task in pending if task.done()}
            for task in completed:
                pending.remove(task)
                task.result()

            capacity = concurrency - len(pending)
            messages = []
            if capacity:
                messages = await asyncio.to_thread(
                    store.claim_stale_uploads,
                    consumer_name,
                    2 * 60 * 60 * 1000,
                    capacity,
                )
                if not messages:
                    messages = await asyncio.to_thread(
                        store.read_uploads,
                        consumer_name,
                        1000,
                        capacity,
                    )
                for message_id, message in messages:
                    pending.add(
                        asyncio.create_task(
                            process_upload_message(
                                store,
                                settings,
                                client,
                                recipient,
                                message_id,
                                message["job_id"],
                            )
                        )
                    )
            if pending and not messages:
                await asyncio.wait(
                    pending,
                    timeout=0.2,
                    return_when=asyncio.FIRST_COMPLETED,
                )
    finally:
        await client.disconnect()


def main():
    settings = load_settings()
    logging.basicConfig(
        format="%(levelname)s - %(asctime)s - %(name)s - %(message)s",
        level=getattr(logging, settings.log_level, logging.INFO),
    )
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        logger.info("Uploader stopped")


if __name__ == "__main__":
    main()
