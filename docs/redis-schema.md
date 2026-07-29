# Redis schema

| Key | Type | Purpose |
| --- | --- | --- |
| `meido:episode:<identity>` | Hash | Cached metadata and Telegram `file_id` |
| `meido:job:<uuid>` | Hash | Persistent job state, attempts, and errors |
| `meido:job-for:<identity>` | String | Active-job deduplication lock |
| `meido:waiters:<uuid>` | Set | Chat IDs waiting for a job |
| `meido:chat-jobs:<chat_id>` | Set | Active job IDs shown in a chat's request menu |
| `meido:jobs` | Stream | Worker job queue |
| `meido:uploads` | Stream | Completed-media upload queue |
| `meido:events` | Stream | Worker-to-bot completion/failure events |
| `meido:job-retries` | Sorted set | Delayed downloader retries |
| `meido:upload-retries` | Sorted set | Delayed Telegram upload retries |
| `meido:progress-messages:<uuid>` | Hash | Chat/message IDs edited for progress |

Episode identity uses:

```text
<normalized-series>:s<season>:e<episode>
```

Jobs, locks, and waiter sets expire after 24 hours. Episode cache entries are
persistent.
