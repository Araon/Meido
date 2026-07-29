#!/usr/bin/env python3
"""Consume Redis jobs and prepare media outside the Telegram bot process."""

from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
import logging
import os
from pathlib import Path
import socket
import sys
from threading import local
import time
from uuid import uuid4

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bot.store import initialize_store
from downloaderService.contracts import AdapterError, DownloadFailed, DownloadRequest
from downloaderService.router import build_downloader
from meido_settings import load_settings


logger = logging.getLogger(__name__)


class ProgressReporter:
    """Throttle downloader/upload updates before publishing them to Redis."""

    def __init__(self, store, job_id, *, clock=None):
        self.store = store
        self.job_id = job_id
        self.clock = clock or time.monotonic
        self.last_phase = None
        self.last_percent = -100
        self.last_emitted_at = 0

    def __call__(self, progress):
        phase = str(progress.get("phase") or "downloading")
        percent = max(0, min(100, int(float(progress.get("percent", 0)))))
        now = self.clock()
        should_emit = (
            phase != self.last_phase
            or percent >= self.last_percent + 5
            or percent == 100
            or now - self.last_emitted_at >= 10
        )
        if not should_emit:
            return
        self.store.publish_progress(
            self.job_id,
            phase=phase,
            percent=percent,
            detail=str(progress.get("detail") or ""),
            backend=str(progress.get("backend") or ""),
        )
        self.last_phase = phase
        self.last_percent = percent
        self.last_emitted_at = now


def download_path(settings, job):
    directory = (
        settings.download_root
        / job["series_key"]
        / f"S{job['season_id']:02d}E{job['episode_id']:02d}"
    )
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def process_job(store, settings, downloader, job_id):
    job = store.get_job(job_id)
    if not job:
        raise LookupError(f"Job not found: {job_id}")

    attempts = int(job.get("attempts", 0)) + 1
    store.update_job(job_id, "downloading", attempts=attempts)
    report_progress = ProgressReporter(store, job_id)
    report_progress(
        {
            "phase": "starting",
            "percent": 0,
            "detail": "Starting download",
        }
    )
    directory = download_path(settings, job)
    try:
        media_file = downloader.download(
            DownloadRequest(
                title=job["series_name"],
                season=job["season_id"],
                episode=job["episode_id"],
                output_dir=directory,
                request_id=job.get("job_id") or uuid4().hex,
                progress_callback=report_progress,
            )
        )
        media_file = Path(media_file).resolve()
        store.update_job(
            job_id,
            "downloaded",
            media_path=str(media_file),
        )
        report_progress(
            {
                "phase": "upload_queued",
                "percent": 100,
                "detail": "Waiting for upload slot",
            }
        )
        store.enqueue_upload(job_id)
    except Exception as error:
        retry_after = retry_delay(error, settings)
        if (
            retry_after is not None
            and attempts < settings.downloader_max_job_attempts
        ):
            retry_at = int(time.time() + retry_after)
            store.schedule_retry(job_id, error, retry_at)
            logger.warning(
                "Job %s failed on attempt %s/%s; retry scheduled in %ss: %s",
                job_id,
                attempts,
                settings.downloader_max_job_attempts,
                retry_after,
                error,
            )
        else:
            store.fail_job(job_id, error)
            logger.exception("Job %s failed permanently", job_id)


def retry_delay(error, settings):
    if not isinstance(error, DownloadFailed):
        return None
    retryable = [
        failure
        for _, failure in error.failures
        if isinstance(failure, AdapterError) and failure.retryable
    ]
    if not retryable:
        return None
    requested_delays = [
        failure.retry_after
        for failure in retryable
        if failure.retry_after is not None
    ]
    if requested_delays:
        return max(
            settings.downloader_retry_delay_seconds,
            min(requested_delays),
        )
    return settings.downloader_retry_delay_seconds


def process_message(
    store,
    settings,
    downloader_state,
    message_id,
    job_id,
):
    """Process one stream message and always release its Redis claim."""
    try:
        if not hasattr(downloader_state, "downloader"):
            downloader_state.downloader = build_downloader(
                settings.downloader_endpoints,
                timeout_seconds=settings.downloader_timeout_seconds,
                cooldown_seconds=settings.downloader_cooldown_seconds,
            )
        process_job(
            store,
            settings,
            downloader_state.downloader,
            job_id,
        )
    except Exception:
        logger.exception("Could not process download message for job %s", job_id)
    finally:
        store.acknowledge_job(message_id)


def main():
    settings = load_settings()
    verifier = build_downloader(
        settings.downloader_endpoints,
        timeout_seconds=settings.downloader_timeout_seconds,
        cooldown_seconds=settings.downloader_cooldown_seconds,
    )
    downloader_descriptions = verifier.verify(require_one=False)
    store = initialize_store(settings.redis_url)
    consumer_name = f"{socket.gethostname()}-{os.getpid()}"
    concurrency = settings.download_concurrency
    downloader_state = local()
    stale_after_ms = (
        settings.downloader_timeout_seconds + 300
    ) * 1000
    logger.info(
        "Worker %s is ready with %s download slots and downloaders: %s",
        consumer_name,
        concurrency,
        ", ".join(downloader_descriptions) or "no sidecar currently ready",
    )

    pending = set()
    with ThreadPoolExecutor(
        max_workers=concurrency,
        thread_name_prefix="meido-download",
    ) as executor:
        while True:
            store.promote_due_retries()
            completed = {future for future in pending if future.done()}
            pending.difference_update(completed)
            capacity = concurrency - len(pending)
            messages = []
            if capacity:
                messages = store.claim_stale_jobs(
                    consumer_name,
                    min_idle_ms=stale_after_ms,
                    count=capacity,
                )
                if not messages:
                    messages = store.read_jobs(
                        consumer_name,
                        block_ms=1000,
                        count=capacity,
                    )
                for message_id, message in messages:
                    pending.add(
                        executor.submit(
                            process_message,
                            store,
                            settings,
                            downloader_state,
                            message_id,
                            message["job_id"],
                        )
                    )
            if pending and not messages:
                wait(
                    pending,
                    timeout=0.2,
                    return_when=FIRST_COMPLETED,
                )


if __name__ == "__main__":
    settings = load_settings()
    logging.basicConfig(
        format="%(levelname)s - %(asctime)s - %(name)s - %(message)s",
        level=getattr(logging, settings.log_level, logging.INFO),
    )
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Worker stopped")
