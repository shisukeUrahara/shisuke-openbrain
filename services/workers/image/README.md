# worker-image

Image ingestion worker. Pops jobs off Redis list `ingest:image`, fetches the image, sends it to a vision-language model (Qwen-VL via OpenRouter by default), captures the response as a document with the OCR text and a short description.

Phase 12.e. Behind `MODULE_WORKERS_IMAGE_ENABLED`.

## Why no local ML

Unlike the audio and PDF workers, the image worker offloads its heavy lifting to OpenRouter's vision-model API. The whole worker is ~150 MB of Python stdlib + httpx + redis — no PyTorch, no model downloads, no GPU. The trade-off: every image incurs a tiny per-call cost on OpenRouter (~$0.001 per image for `qwen/qwen-2.5-vl-7b-instruct`).

If you want to swap in a local VLM (e.g. Qwen-VL via Ollama or a llama.cpp variant), the `VisionAnalyzer` Protocol in `analyzer.py` is the seam.

## Job payload shapes

```json
{ "url": "https://example.com/photo.jpg", "caption": "optional" }
```

```json
{ "path": "/data/snaps/IMG_001.jpg", "caption": "optional" }
```

```json
{ "file_id": "...telegram...", "caption": "optional" }
```

`caption` is optional context the Telegram user attached to the photo. It propagates into the prompt so the VLM knows what the user cared about. The Telegram bot pushes `file_id` payloads; like the other workers, those get a clear skip until `TELEGRAM_BOT_TOKEN` is wired in.

## What lands in the brain

The worker captures one `document` per image (kind = `image`) whose `content_md` follows this template:

```markdown
> User caption: <whatever the user typed>

## Extracted Text
<verbatim OCR of any text visible in the image>

## Description
<2-4 sentence description of what the image shows>
```

The chunker then splits long results into chunks like any other document, so semantic search works the same way as for articles or PDFs.

## Configuration

| Env var | Required when | Purpose |
|---|---|---|
| `MODULE_WORKERS_IMAGE_ENABLED` | always | Master flag |
| `BRAIN_URL` | flag on | Full MCP URL with `?key=` |
| `REDIS_URL` | flag on | Redis DSN |
| `OPENROUTER_API_KEY` | flag on | OpenRouter key for the VLM call |
| `WORKER_VISION_MODEL` | optional | Default `qwen/qwen-2.5-vl-7b-instruct` |
| `WORKER_MAX_IMAGE_BYTES` | optional | Default 10 MB |
| `WORKER_MAX_CHUNK_TOKENS` | optional | Default 800 |
| `WORKER_CHUNK_OVERLAP_TOKENS` | optional | Default 120 |

## Local dev

```bash
docker compose --profile image build worker-image    # ~150 MB image
docker compose --profile image up -d
docker compose --profile image exec redis redis-cli LPUSH ingest:image \
  '{"url":"https://upload.wikimedia.org/wikipedia/commons/4/47/PNG_transparency_demonstration_1.png"}'
docker compose --profile image logs -f worker-image
```

## Layout

```
src/worker_image/
├── __init__.py
├── config.py        # env + features.yaml
├── chunker.py       # paragraph-based markdown chunker
├── fetcher.py       # url/path/telegram-skip
├── analyzer.py      # VisionAnalyzer Protocol + OpenRouterVisionAnalyzer
├── mcp_client.py    # JSON-RPC wrapper (isError-aware)
├── queue.py         # redis BRPOP wrapper
└── worker.py        # process_one + main loop
```
