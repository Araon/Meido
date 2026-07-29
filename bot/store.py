"""Redis-backed cache, job queue, and worker coordination."""

from datetime import datetime, timezone
import logging
import time
from uuid import uuid4

from redis import Redis
from redis.exceptions import ResponseError


logger = logging.getLogger(__name__)

JOB_STREAM = "meido:jobs"
JOB_GROUP = "meido-workers"
UPLOAD_STREAM = "meido:uploads"
UPLOAD_GROUP = "meido-uploaders"
EVENT_STREAM = "meido:events"
EVENT_GROUP = "meido-bot"
RETRY_ZSET = "meido:job-retries"
UPLOAD_RETRY_ZSET = "meido:upload-retries"
JOB_TTL_SECONDS = 24 * 60 * 60


def episode_key(series_key, season_id, episode_id):
    return f"{series_key}:s{int(season_id)}:e{int(episode_id)}"


def chat_jobs_key(chat_id):
    return f"meido:chat-jobs:{int(chat_id)}"


def _now():
    return datetime.now(timezone.utc).isoformat()


class RedisStore:
    def __init__(self, redis_url):
        self.client = Redis.from_url(
            redis_url,
            decode_responses=True,
            socket_connect_timeout=2,
            # Must exceed the worker's five-second blocking Stream read.
            socket_timeout=10,
        )

    def ping(self):
        return bool(self.client.ping())

    def ensure_groups(self):
        for stream, group in (
            (JOB_STREAM, JOB_GROUP),
            (UPLOAD_STREAM, UPLOAD_GROUP),
            (EVENT_STREAM, EVENT_GROUP),
        ):
            try:
                self.client.xgroup_create(stream, group, id="0", mkstream=True)
            except ResponseError as error:
                if "BUSYGROUP" not in str(error):
                    raise

    def get_episode(self, series_key, season_id, episode_id):
        key = f"meido:episode:{episode_key(series_key, season_id, episode_id)}"
        data = self.client.hgetall(key)
        if not data:
            return None
        for field in ("season_id", "episode_id", "times_queried"):
            if field in data:
                data[field] = int(data[field])
        return data

    def increment_episode_queries(self, series_key, season_id, episode_id):
        key = f"meido:episode:{episode_key(series_key, season_id, episode_id)}"
        return self.client.hincrby(key, "times_queried", 1)

    def cache_episode(self, job, file_id):
        identity = episode_key(
            job["series_key"],
            job["season_id"],
            job["episode_id"],
        )
        key = f"meido:episode:{identity}"
        self.client.hset(
            key,
            mapping={
                "series_key": job["series_key"],
                "series_name": job["series_name"],
                "season_id": job["season_id"],
                "episode_id": job["episode_id"],
                "file_id": file_id,
                "times_queried": 0,
                "date_added": _now(),
            },
        )

    def enqueue_episode(
        self,
        *,
        series_key,
        series_name,
        season_id,
        episode_id,
        chat_id,
    ):
        identity = episode_key(series_key, season_id, episode_id)
        lock_key = f"meido:job-for:{identity}"
        job_id = uuid4().hex

        if not self.client.set(lock_key, job_id, nx=True, ex=JOB_TTL_SECONDS):
            existing_job_id = self.client.get(lock_key)
            if existing_job_id:
                self._add_waiter(existing_job_id, chat_id)
                return existing_job_id, False
            return self.enqueue_episode(
                series_key=series_key,
                series_name=series_name,
                season_id=season_id,
                episode_id=episode_id,
                chat_id=chat_id,
            )

        job = {
            "job_id": job_id,
            "identity": identity,
            "series_key": series_key,
            "series_name": series_name,
            "season_id": season_id,
            "episode_id": episode_id,
            "status": "queued",
            "created_at": _now(),
            "updated_at": _now(),
        }
        try:
            pipeline = self.client.pipeline(transaction=True)
            pipeline.hset(f"meido:job:{job_id}", mapping=job)
            pipeline.expire(f"meido:job:{job_id}", JOB_TTL_SECONDS)
            pipeline.sadd(f"meido:waiters:{job_id}", str(chat_id))
            pipeline.expire(f"meido:waiters:{job_id}", JOB_TTL_SECONDS)
            pipeline.sadd(chat_jobs_key(chat_id), job_id)
            pipeline.expire(chat_jobs_key(chat_id), JOB_TTL_SECONDS)
            pipeline.xadd(JOB_STREAM, {"job_id": job_id})
            pipeline.execute()
        except Exception:
            self.client.delete(lock_key)
            raise
        return job_id, True

    def _add_waiter(self, job_id, chat_id):
        key = f"meido:waiters:{job_id}"
        pipeline = self.client.pipeline()
        pipeline.sadd(key, str(chat_id))
        pipeline.expire(key, JOB_TTL_SECONDS)
        pipeline.sadd(chat_jobs_key(chat_id), job_id)
        pipeline.expire(chat_jobs_key(chat_id), JOB_TTL_SECONDS)
        pipeline.execute()

    def get_job(self, job_id):
        job = self.client.hgetall(f"meido:job:{job_id}")
        if not job:
            return None
        for field in ("season_id", "episode_id"):
            if field in job:
                job[field] = int(job[field])
        return job

    def update_job(self, job_id, status, **fields):
        mapping = {"status": status, "updated_at": _now()}
        mapping.update({key: str(value) for key, value in fields.items()})
        self.client.hset(f"meido:job:{job_id}", mapping=mapping)

    def get_waiters(self, job_id):
        return sorted(int(chat_id) for chat_id in self.client.smembers(
            f"meido:waiters:{job_id}"
        ))

    def get_active_jobs(self, chat_id):
        key = chat_jobs_key(chat_id)
        jobs = []
        stale = []
        for job_id in self.client.smembers(key):
            job = self.get_job(job_id)
            if not job or job.get("status") in {"ready", "failed"}:
                stale.append(job_id)
                continue
            jobs.append(job)
        if stale:
            self.client.srem(key, *stale)
        return sorted(
            jobs,
            key=lambda job: job.get("created_at", ""),
            reverse=True,
        )

    def remove_waiter(self, job_id, chat_id):
        pipeline = self.client.pipeline()
        pipeline.srem(f"meido:waiters:{job_id}", str(chat_id))
        pipeline.srem(chat_jobs_key(chat_id), job_id)
        removed_waiter, _ = pipeline.execute()
        return bool(removed_waiter)

    def set_progress_message(self, job_id, chat_id, message_id):
        key = f"meido:progress-messages:{job_id}"
        pipeline = self.client.pipeline()
        pipeline.hset(key, str(chat_id), str(message_id))
        pipeline.expire(key, JOB_TTL_SECONDS)
        pipeline.execute()

    def get_progress_messages(self, job_id):
        messages = self.client.hgetall(
            f"meido:progress-messages:{job_id}"
        )
        return {
            int(chat_id): int(message_id)
            for chat_id, message_id in messages.items()
        }

    def clear_progress_messages(self, job_id):
        self.client.delete(f"meido:progress-messages:{job_id}")

    def remove_progress_message(self, job_id, chat_id):
        return bool(
            self.client.hdel(
                f"meido:progress-messages:{job_id}",
                str(chat_id),
            )
        )

    def publish_progress(
        self,
        job_id,
        *,
        phase,
        percent,
        detail="",
        backend="",
    ):
        percent = max(0, min(100, int(percent)))
        if phase == "uploading":
            status = "uploading"
        elif phase == "awaiting_bot":
            status = "awaiting_bot"
        elif phase == "validating":
            status = "validating"
        elif phase == "upload_queued":
            status = "upload_queued"
        else:
            status = "downloading"
        self.update_job(
            job_id,
            status,
            phase=phase,
            progress_percent=percent,
            progress_detail=detail[:200],
            backend=backend[:100],
        )
        self.client.xadd(
            EVENT_STREAM,
            {
                "event": "job_progress",
                "job_id": job_id,
                "phase": phase,
                "percent": percent,
                "detail": detail[:200],
                "backend": backend[:100],
            },
            maxlen=1000,
            approximate=True,
        )

    def complete_job(self, job_id, file_id):
        job = self.get_job(job_id)
        if not job:
            return []
        self.cache_episode(job, file_id)
        self.update_job(job_id, "ready", file_id=file_id)
        waiters = self.get_waiters(job_id)
        pipeline = self.client.pipeline()
        pipeline.delete(f"meido:job-for:{job['identity']}")
        pipeline.delete(f"meido:waiters:{job_id}")
        for chat_id in waiters:
            pipeline.srem(chat_jobs_key(chat_id), job_id)
        pipeline.execute()
        return waiters

    def fail_job(self, job_id, error):
        job = self.get_job(job_id)
        if not job:
            return
        self.update_job(job_id, "failed", error=str(error)[:500])
        self.client.delete(f"meido:job-for:{job['identity']}")
        self.client.xadd(
            EVENT_STREAM,
            {"event": "job_failed", "job_id": job_id},
        )

    def schedule_retry(self, job_id, error, retry_at):
        self.update_job(
            job_id,
            "retry_scheduled",
            last_error=str(error)[:500],
            retry_at=retry_at,
        )
        self.client.zadd(RETRY_ZSET, {job_id: float(retry_at)})

    def enqueue_upload(self, job_id):
        self.update_job(job_id, "upload_queued")
        self.client.xadd(UPLOAD_STREAM, {"job_id": job_id})

    def schedule_upload_retry(self, job_id, error, retry_at):
        self.update_job(
            job_id,
            "upload_retry_scheduled",
            upload_last_error=str(error)[:500],
            upload_retry_at=retry_at,
        )
        self.client.zadd(UPLOAD_RETRY_ZSET, {job_id: float(retry_at)})

    def promote_due_retries(self, now=None, limit=20):
        now = time.time() if now is None else float(now)
        job_ids = self.client.zrangebyscore(
            RETRY_ZSET,
            "-inf",
            now,
            start=0,
            num=limit,
        )
        promoted = []
        for job_id in job_ids:
            # ZREM elects one worker when several workers poll simultaneously.
            if self.client.zrem(RETRY_ZSET, job_id):
                self.update_job(job_id, "queued", retry_at="")
                self.client.xadd(JOB_STREAM, {"job_id": job_id})
                promoted.append(job_id)
        return promoted

    def promote_due_upload_retries(self, now=None, limit=20):
        now = time.time() if now is None else float(now)
        job_ids = self.client.zrangebyscore(
            UPLOAD_RETRY_ZSET,
            "-inf",
            now,
            start=0,
            num=limit,
        )
        promoted = []
        for job_id in job_ids:
            if self.client.zrem(UPLOAD_RETRY_ZSET, job_id):
                self.update_job(
                    job_id,
                    "upload_queued",
                    upload_retry_at="",
                )
                self.client.xadd(UPLOAD_STREAM, {"job_id": job_id})
                promoted.append(job_id)
        return promoted

    def take_failed_waiters(self, job_id):
        waiters = self.get_waiters(job_id)
        pipeline = self.client.pipeline()
        pipeline.delete(f"meido:waiters:{job_id}")
        for chat_id in waiters:
            pipeline.srem(chat_jobs_key(chat_id), job_id)
        pipeline.execute()
        return waiters

    def read_jobs(self, consumer_name, block_ms=5000, count=1):
        messages = self.client.xreadgroup(
            JOB_GROUP,
            consumer_name,
            {JOB_STREAM: ">"},
            count=count,
            block=block_ms,
        )
        if not messages:
            return []
        return messages[0][1]

    def read_uploads(self, consumer_name, block_ms=5000, count=1):
        messages = self.client.xreadgroup(
            UPLOAD_GROUP,
            consumer_name,
            {UPLOAD_STREAM: ">"},
            count=count,
            block=block_ms,
        )
        if not messages:
            return []
        return messages[0][1]

    def claim_stale_jobs(
        self,
        consumer_name,
        min_idle_ms=60_000,
        count=10,
    ):
        result = self.client.xautoclaim(
            JOB_STREAM,
            JOB_GROUP,
            consumer_name,
            min_idle_ms,
            start_id="0-0",
            count=count,
        )
        if not result:
            return []
        return result[1]

    def claim_stale_uploads(
        self,
        consumer_name,
        min_idle_ms=60_000,
        count=10,
    ):
        result = self.client.xautoclaim(
            UPLOAD_STREAM,
            UPLOAD_GROUP,
            consumer_name,
            min_idle_ms,
            start_id="0-0",
            count=count,
        )
        if not result:
            return []
        return result[1]

    def acknowledge_job(self, message_id):
        self.client.xack(JOB_STREAM, JOB_GROUP, message_id)

    def acknowledge_upload(self, message_id):
        self.client.xack(UPLOAD_STREAM, UPLOAD_GROUP, message_id)

    def read_events(self, consumer_name, count=20):
        messages = self.client.xreadgroup(
            EVENT_GROUP,
            consumer_name,
            {EVENT_STREAM: ">"},
            count=count,
            block=1,
        )
        if not messages:
            return []
        return messages[0][1]

    def acknowledge_event(self, message_id):
        self.client.xack(EVENT_STREAM, EVENT_GROUP, message_id)


def initialize_store(redis_url, max_attempts=5, retry_delay=1.0):
    store = RedisStore(redis_url)
    for attempt in range(1, max_attempts + 1):
        try:
            store.ping()
            store.ensure_groups()
            logger.info("Connected to Redis")
            return store
        except Exception as error:
            if attempt == max_attempts:
                raise ConnectionError(
                    f"Redis unavailable after {max_attempts} attempts"
                ) from error
            logger.warning(
                "Redis connection attempt %s/%s failed: %s",
                attempt,
                max_attempts,
                error,
            )
            time.sleep(retry_delay)
    raise ConnectionError("Redis initialization failed")
