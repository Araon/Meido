# Architecture

## Services

### Bot

The bot validates Telegram commands, returns cached `file_id` values, and
queues cache misses in Redis. It never invokes a downloader, FFmpeg, or
Telethon.

### Redis

Redis is both the persistent cache and coordination layer:

- Episode hashes store Telegram `file_id` values.
- Job hashes store lifecycle and error information.
- A Redis Stream distributes work to media workers.
- A Redis sorted set holds delayed retries.
- Per-episode locks deduplicate simultaneous requests.
- Waiter sets record every chat awaiting the same episode.

Append-only persistence is enabled by Compose.

### Download worker

The download worker consumes Redis Stream jobs and talks only to the downloader
contract. A bounded thread pool prepares multiple episodes concurrently and
places validated files on a separate Redis upload stream.

### Telegram uploader

The uploader owns one authorized Telethon user session. It resolves
`TELEGRAM_BOT_USERNAME` at startup and rejects the configuration unless the
peer is a bot. A bounded asyncio task set uploads multiple completed episodes
through the same client without sharing a SQLite session between processes.
Each video's caption contains an opaque job ID.

### Downloader router

The router receives explicit title, season, episode, language, quality, and
request ID fields. It tries HTTP adapters in the order configured by
`DOWNLOADER_ENDPOINTS`. Every attempt uses a separate temporary directory, so
partial output cannot affect a fallback.

The first sidecar pins anime-sdk 1.1.0 in a Node 22 image and currently exposes
AnimeParadise, Gogo/Anineko, Anikoto, and MegaPlay. The worker contains no
provider library. It streams the response to a partial file, validates a video
stream with FFprobe, and atomically promotes the result.

HLS segments are fetched in small ordered batches. The default concurrency is
three and the accepted range is one through eight. Segment buffers are written
in playlist order before FFmpeg remuxes the transport stream.

Adapters return typed errors. Missing titles and unsupported requests fall
through without opening a circuit. Challenges, rate limits, and temporary
network failures cool the backend down. Job retries are placed in a Redis
sorted set and promoted later instead of immediately repeating the complete
provider chain.

See `docs/downloader-adapters.md` for the target multi-adapter topology,
failure semantics, and promotion criteria.

Sidecar readiness is observational rather than permanent. The worker can start
when a sidecar is temporarily unavailable and will use it after recovery. If
every adapter fails a job, the stored error identifies every attempt.

### Completion

The bot accepts video or video-document uploads only from
`TELEGRAM_AGENT_USER_ID`. It resolves the job ID through Redis, stores the
resulting Telegram `file_id`, and sends the video to all waiting chats. A 100%
Telethon upload is shown as `awaiting_bot`; only this bot acknowledgement makes
the job `ready`.

## Job states

```text
queued -> downloading -> upload_queued -> uploading -> awaiting_bot -> ready
             |                |              |
             v                v              v
      retry_scheduled   upload retry      failed
             |
             +-----------------> queued
```

Only aggregate retryable failures are scheduled again. Permanent and semantic
failures are emitted on a Redis event stream so the bot can notify waiting
users.
