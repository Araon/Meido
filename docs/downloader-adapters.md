# Downloader adapters

The downloader layer is a replaceable boundary. Telegram, Redis job handling,
and uploads must not import a scraper library or know provider-specific flags.

## Target topology

```text
Media worker / router
    |
    +-- anime-sdk service
    +-- future independent service
    +-- future independent service
```

Use three to five configured adapters. Each implementation with its own
dependencies runs in a separate Compose service and image. This provides real
dependency, build, crash, upgrade, and resource isolation without nested
virtual environments in the worker image.

Adapters share a versioned internal contract:

- `GET /health/live` reports process liveness.
- `GET /health/ready` reports pinned runtime and enabled providers.
- `POST /v1/download` accepts contract version, backend, title, season,
  episode, language, quality, request ID, and optional sample duration.
- A successful response streams a normalized MP4 to the worker.
- Failure responses distinguish `not_found`, `blocked`, `rate_limited`,
  `temporary`, and `permanent`.

Only Compose's private network exposes these APIs. Downloader services have no
Telegram credentials, sessions, Redis access, or writable worker volume.

The anime-sdk adapter fetches HLS segments in bounded parallel batches while
writing them in playlist order. `ANIME_SDK_SEGMENT_CONCURRENCY` defaults to
three and is capped at eight to limit rate-limit and memory pressure.

## Router behavior

The router:

1. Uses the order in `DOWNLOADER_ENDPOINTS`.
2. Skips unhealthy adapters.
3. Gives each attempt an isolated temporary directory.
4. Falls back only for retryable provider/runtime failures.
5. Stops for invalid input or a confirmed missing episode.
6. Opens a cooldown circuit after repeated failures.
7. Schedules aggregate retryable failures through Redis instead of retrying
   immediately.

An adapter is promoted into the configured list only after this passes:

```bash
docker compose run --rm --no-deps worker \
  python -m downloaderService.smoke_test "Death Note" 3 \
  --season 1 --backend animeparadise
```

The Telegram bot is started only after at least one end-to-end downloader smoke
test succeeds.

## Current status

Animdl and anipy-api have been removed from the worker. On 2026-07-30, isolated
Death Note S01E03 smoke tests produced valid MP4 samples through AnimeParadise,
Gogo/Anineko, Anikoto, and MegaPlay. A complete AnimeParadise episode also
passed worker-side FFprobe validation. AllManga failed and is not configured.

Anikoto and MegaPlay currently resolve to the same media host, so they should
be treated as two provider integrations but one likely CDN failure domain.
