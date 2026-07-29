"""Tests for Redis persistence and queue coordination."""

from unittest.mock import patch

import fakeredis

from bot.store import RedisStore, initialize_store


def fake_store():
    store = RedisStore.__new__(RedisStore)
    store.client = fakeredis.FakeRedis(decode_responses=True)
    store.ensure_groups()
    return store


def test_episode_cache_round_trip():
    store = fake_store()
    job = {
        "series_key": "death_note",
        "series_name": "Death Note",
        "season_id": 1,
        "episode_id": 3,
    }

    store.cache_episode(job, "file-id")
    result = store.get_episode("death_note", 1, 3)

    assert result["file_id"] == "file-id"
    assert result["season_id"] == 1
    assert result["episode_id"] == 3


def test_duplicate_episode_uses_one_job_and_two_waiters():
    store = fake_store()
    request = {
        "series_key": "death_note",
        "series_name": "Death Note",
        "season_id": 1,
        "episode_id": 3,
    }

    first_job, first_created = store.enqueue_episode(**request, chat_id=111)
    second_job, second_created = store.enqueue_episode(**request, chat_id=222)

    assert first_created is True
    assert second_created is False
    assert second_job == first_job
    assert store.get_waiters(first_job) == [111, 222]


def test_complete_job_caches_file_and_returns_waiters():
    store = fake_store()
    job_id, _ = store.enqueue_episode(
        series_key="death_note",
        series_name="Death Note",
        season_id=1,
        episode_id=3,
        chat_id=111,
    )

    waiters = store.complete_job(job_id, "file-id")

    assert waiters == [111]
    assert store.get_episode("death_note", 1, 3)["file_id"] == "file-id"
    assert store.client.get("meido:job-for:death_note:s1:e3") is None


def test_progress_messages_and_events_round_trip():
    store = fake_store()
    job_id, _ = store.enqueue_episode(
        series_key="death_note",
        series_name="Death Note",
        season_id=1,
        episode_id=3,
        chat_id=111,
    )
    store.set_progress_message(job_id, 111, 555)
    store.publish_progress(
        job_id,
        phase="downloading",
        percent=42,
        detail="Segment 42/100",
        backend="animeparadise",
    )

    assert store.get_progress_messages(job_id) == {111: 555}
    assert store.get_job(job_id)["progress_percent"] == "42"
    events = store.read_events("progress-bot")
    assert events[0][1]["event"] == "job_progress"
    assert events[0][1]["percent"] == "42"

    store.clear_progress_messages(job_id)
    assert store.get_progress_messages(job_id) == {}


def test_failed_job_emits_event():
    store = fake_store()
    job_id, _ = store.enqueue_episode(
        series_key="death_note",
        series_name="Death Note",
        season_id=1,
        episode_id=3,
        chat_id=111,
    )

    store.fail_job(job_id, "provider unavailable")
    events = store.read_events("test-bot")

    assert events[0][1] == {
        "event": "job_failed",
        "job_id": job_id,
    }
    assert store.get_job(job_id)["status"] == "failed"


def test_worker_can_claim_stale_pending_job():
    store = fake_store()
    job_id, _ = store.enqueue_episode(
        series_key="death_note",
        series_name="Death Note",
        season_id=1,
        episode_id=3,
        chat_id=111,
    )
    messages = store.read_jobs("dead-worker")
    assert messages[0][1]["job_id"] == job_id

    claimed = store.claim_stale_jobs("replacement-worker", min_idle_ms=0)

    assert claimed[0][1]["job_id"] == job_id


def test_scheduled_retry_is_promoted_only_when_due():
    store = fake_store()
    job_id, _ = store.enqueue_episode(
        series_key="death_note",
        series_name="Death Note",
        season_id=1,
        episode_id=3,
        chat_id=111,
    )
    # Remove the initial message so only the delayed retry is observed.
    initial = store.read_jobs("initial-worker")
    store.acknowledge_job(initial[0][0])
    store.schedule_retry(job_id, "temporary", retry_at=200)

    assert store.promote_due_retries(now=199) == []
    assert store.promote_due_retries(now=200) == [job_id]
    messages = store.read_jobs("retry-worker", block_ms=1)

    assert messages[0][1]["job_id"] == job_id
    assert store.get_job(job_id)["status"] == "queued"


def test_upload_queue_and_retry_round_trip():
    store = fake_store()
    job_id, _ = store.enqueue_episode(
        series_key="death_note",
        series_name="Death Note",
        season_id=1,
        episode_id=3,
        chat_id=111,
    )
    store.enqueue_upload(job_id)

    messages = store.read_uploads("uploader", block_ms=1)
    assert messages[0][1]["job_id"] == job_id
    store.acknowledge_upload(messages[0][0])

    store.schedule_upload_retry(job_id, "offline", retry_at=200)
    assert store.promote_due_upload_retries(now=199) == []
    assert store.promote_due_upload_retries(now=200) == [job_id]
    retried = store.read_uploads("retry-uploader", block_ms=1)
    assert retried[0][1]["job_id"] == job_id


def test_initialize_store_retries():
    with patch("bot.store.RedisStore") as store_class, patch(
        "bot.store.time.sleep"
    ) as sleep:
        store = store_class.return_value
        store.ping.side_effect = [ConnectionError("offline"), True]

        result = initialize_store("redis://test", max_attempts=2, retry_delay=0.1)

    assert result is store
    assert store.ping.call_count == 2
    store.ensure_groups.assert_called_once_with()
    sleep.assert_called_once_with(0.1)
