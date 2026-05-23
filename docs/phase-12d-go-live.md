# Phase 12.d — Audio + YouTube Worker Go-Live (Operator Guide)

The audio worker is fully built and tested locally. Live ingestion needs:

1. `OPENROUTER_API_KEY` on the MCP server (same key from Phase 12.b — wire once, reused everywhere).
2. `MODULE_WORKERS_AUDIO_ENABLED=true` in `.env`.
3. The `audio` compose profile is up.
4. ~250 MB of free disk for the whisper model on first job.

## Step 1 — Enable + start

```bash
grep -q '^MODULE_WORKERS_AUDIO_ENABLED=' .env \
  && sed -i 's|^MODULE_WORKERS_AUDIO_ENABLED=.*$|MODULE_WORKERS_AUDIO_ENABLED=true|' .env \
  || echo 'MODULE_WORKERS_AUDIO_ENABLED=true' >> .env

# Heavy build (~1 GB): ffmpeg + libsndfile + faster-whisper + ctranslate2 + yt-dlp.
docker compose --profile audio build worker-audio

docker compose --profile audio up -d
```

## Step 2 — Push a YouTube link (fastest first test)

```bash
docker compose --profile audio exec redis redis-cli LPUSH ingest:youtube \
  '{"url":"https://www.youtube.com/watch?v=jNQXAC9IVRw","project":"test"}'   # 19-second clip
```

## Step 3 — Watch it process

```bash
docker compose --profile audio logs -f worker-audio
```

First job timeline (on 2 vCPUs):

```
audio worker ready, queues=[ingest:voice, ingest:youtube], model=small, ...
[yt-dlp output ...]                              # ~3-5s for short clips
loading faster-whisper model=small ...           # ~30-60s, FIRST job only
[transcribing]                                   # ~1x realtime → 19-sec clip ≈ 15s
job done (ingest:youtube): {'status': 'ingested', ..., 'chunks': 1, 'duration_s': 19.0, ...}
```

Subsequent jobs skip the model load. Expect roughly real-time transcription for English content on CPU; multilingual is slightly slower.

## Step 4 — Push a local voice note

```bash
# Drop an audio file into the worker container
docker cp ~/voice-notes/idea.ogg openbrain-worker-audio:/tmp/idea.ogg
docker compose --profile audio exec redis redis-cli LPUSH ingest:voice \
  '{"path":"/tmp/idea.ogg","title":"morning idea"}'
```

Supported formats: anything ffmpeg can decode (mp3, wav, m4a, ogg, opus, flac, webm).

## Step 5 — Verify in Postgres

```bash
PGPASSWORD=devpass psql -h localhost -U postgres -d openbrain <<'SQL'
\x
SELECT title, kind, source, metadata->>'language' AS lang,
       metadata->>'duration_s' AS duration, project, created_at
FROM documents
WHERE kind IN ('voice', 'youtube')
ORDER BY created_at DESC LIMIT 5;

SELECT count(*) AS chunks_total,
       count(*) FILTER (WHERE embedding IS NOT NULL) AS chunks_embedded
FROM chunks c
JOIN documents d ON d.id = c.document_id
WHERE d.kind IN ('voice', 'youtube');
SQL
```

## Step 6 — Search transcribed content from Claude Code

```
"Use search_chunks against openbrain-local for passages about <topic mentioned in the video/note>."
```

Hits come back with `document_kind=youtube` or `document_kind=voice`, with the source URL or local path attached for citation.

## Whisper model selection

| Model | Disk | Speed (CPU) | Quality |
|---|---|---|---|
| `tiny`   | 75 MB  | ~5-7x realtime | poor for accents/noise |
| `base`   | 145 MB | ~3-4x realtime | OK for clean English |
| `small`  | 250 MB | ~1x realtime   | good for multilingual including Hindi |
| `medium` | 750 MB | ~0.4x realtime | very good — needs ≥ 8 GB RAM |
| `large-v3` | 1.5 GB | ~0.1x realtime on CPU; ~10x realtime on GPU |

Set via `.env`:
```
WORKER_WHISPER_MODEL=small        # default
WORKER_WHISPER_COMPUTE_TYPE=int8  # default for CPU; use float16 on GPU
```

Restart the worker after changing the model: `docker compose --profile audio up -d --force-recreate worker-audio`.

## Limits

| Limit | Default | Override |
|---|---|---|
| Max download size | 200 MB | `WORKER_MAX_AUDIO_BYTES` |
| Max chunk tokens | 800 | `WORKER_MAX_CHUNK_TOKENS` |
| Chunk overlap tokens | 120 | `WORKER_CHUNK_OVERLAP_TOKENS` |
| yt-dlp timeout | none enforced | yt-dlp's own defaults |

## Troubleshooting

| Symptom | Fix |
|---|---|
| `yt-dlp failed for URL` | YouTube changed its internals. `pip install -U yt-dlp` inside the container, or rebuild the image. |
| `transcribe failed: ... CTranslate2 ...` | Compute type mismatch. `int8` works on every CPU. `float16` needs a GPU container. Reset to `int8`. |
| First job hangs for minutes | Model download in progress (~250 MB for `small`). Check container disk and network. Subsequent jobs skip this. |
| `not yet supported: telegram file_id` | Documented gap. The Telegram bot pushes `file_id` for voice notes but the worker has no `TELEGRAM_BOT_TOKEN` to download them. Route via `{path}` until the follow-up lands. |
| `empty transcript` skip | Audio file is silent or all VAD-filtered out. Confirm there is speech in the file. |
| `capture_document tool error: OPENROUTER_API_KEY` | Same as the other workers — add the key to `.env`, recreate mcp-server. |

## Costs

Embedding cost: same `text-embedding-3-small` rate as articles. A 20-minute YouTube video transcribes to roughly 3,000-5,000 words → 10-20 chunks → ~$0.0005 to embed. faster-whisper itself runs locally and costs only CPU time.

## Telegram-side handoff

Same gap as the PDF worker: the Telegram bot classifies voice notes and pushes a `{file_id, duration_s, message_id}` payload but the worker cannot download from Telegram yet. Until the `TELEGRAM_BOT_TOKEN`-aware follow-up lands, route voice notes via path-mode payloads (drop the file into a shared volume and push `{path: ...}`).
