# worker-audio

Audio + YouTube ingestion worker. Pops jobs off Redis lists `ingest:voice` and `ingest:youtube`, fetches the source, transcribes with [faster-whisper](https://github.com/SYSTRAN/faster-whisper), chunks the transcript, and calls the MCP server's `capture_document` + `add_chunks` tools.

Phase 12.d. Behind `MODULE_WORKERS_AUDIO_ENABLED`.

## Job payload shapes

YouTube (uses yt-dlp to grab the best audio track):
```json
{ "url": "https://www.youtube.com/watch?v=...", "project": "optional" }
```

Telegram voice note placeholder (worker downloads from Telegram once `TELEGRAM_BOT_TOKEN` is wired into the worker — currently the bot pushes the metadata but the worker logs "missing telegram token" and skips):
```json
{ "file_id": "...", "duration_s": 42, "message_id": 123 }
```

Local audio file (already on a shared volume):
```json
{ "path": "/data/voice-notes/clip.mp3", "title": "optional" }
```

## Why faster-whisper

- 5-10x faster than reference OpenAI Whisper at equivalent quality, using CTranslate2 for inference.
- CPU-only execution works out of the box (no CUDA required).
- Models download lazily on first transcription and persist via the `whisper_models` named volume so container restarts do not re-download.

Default model is `small` (~250 MB, multilingual, good English/Hindi quality, runs realtime on 2 vCPUs). Override with `WORKER_WHISPER_MODEL=tiny|base|small|medium|large-v3`. Larger = slower but better. `medium` is the sweet spot if you have a CX32 or larger box; `large-v3` only makes sense on a real GPU.

## Pipeline

```
LPUSH ingest:youtube → worker-audio
LPUSH ingest:voice   → worker-audio (path or file_id)
                          ├── fetcher: youtube? yt-dlp → /tmp/<sha>.mp3
                          │            path?    -> verify exists
                          │            file_id? -> not yet supported
                          ├── transcriber: faster-whisper.transcribe()
                          ├── chunker:     paragraph-based on segment boundaries
                          └── mcp client:
                                 capture_document(kind="youtube" or "voice")
                                 add_chunks(batch=8)
```

## Configuration

| Env var | Required when | Purpose |
|---|---|---|
| `MODULE_WORKERS_AUDIO_ENABLED` | always | Master flag |
| `BRAIN_URL` | flag on | Full MCP URL with `?key=` |
| `REDIS_URL` | flag on | Redis DSN |
| `WORKER_QUEUE_VOICE` | optional | Default `ingest:voice` |
| `WORKER_QUEUE_YOUTUBE` | optional | Default `ingest:youtube` |
| `WORKER_WHISPER_MODEL` | optional | Default `small` |
| `WORKER_WHISPER_COMPUTE_TYPE` | optional | Default `int8` (cpu); set `float16` on GPU |
| `WORKER_MAX_AUDIO_BYTES` | optional | Default 200 MB |
| `WORKER_MAX_CHUNK_TOKENS` | optional | Default 800 |
| `WORKER_CHUNK_OVERLAP_TOKENS` | optional | Default 120 |

## Local dev

```bash
docker compose --profile audio build worker-audio    # ~1 GB image (ffmpeg + ctranslate2)
docker compose --profile audio up -d
docker compose --profile audio exec redis redis-cli LPUSH ingest:youtube \
  '{"url":"https://www.youtube.com/watch?v=jNQXAC9IVRw"}'   # 19-sec video for a quick first test
docker compose --profile audio logs -f worker-audio
```

First transcription downloads the whisper model (~250 MB for `small`) — subsequent jobs skip the download. Expect ~5 minutes for a 20-minute video on 2 vCPUs.

## Layout

```
src/worker_audio/
├── __init__.py
├── config.py        # env + features.yaml + whisper model selection
├── chunker.py       # paragraph-based markdown chunker
├── fetcher.py       # youtube via yt-dlp | path mode | file_id skip
├── transcriber.py   # faster-whisper wrapper behind a Protocol
├── mcp_client.py    # JSON-RPC wrapper
├── queue.py         # redis BRPOP wrapper, supports multiple queues
└── worker.py        # process_one + main loop polling both queues
```
