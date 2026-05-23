FROM python:3.12-slim AS base

# faster-whisper needs libsndfile1 for audio decoding. yt-dlp shells
# out to ffmpeg for muxing. ca-certificates lets httpx verify TLS.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      ca-certificates \
      ffmpeg \
      libsndfile1 \
 && rm -rf /var/lib/apt/lists/* \
 && pip install --no-cache-dir uv

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
RUN uv pip install --system --no-cache .

# faster-whisper caches model weights under ~/.cache/huggingface.
# Operators mount a named volume here so models survive container
# restarts (saves ~250 MB+ re-download per recycle).
ENV HOME=/root
VOLUME ["/root/.cache/huggingface"]

CMD ["python", "-m", "worker_audio.worker"]
