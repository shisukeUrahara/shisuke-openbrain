FROM python:3.12-slim AS base

# Docling needs libgomp1 + a few image-processing libs to install
# cleanly. ca-certificates lets httpx verify TLS.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      ca-certificates \
      libgomp1 \
      libgl1 \
      libglib2.0-0 \
 && rm -rf /var/lib/apt/lists/* \
 && pip install --no-cache-dir uv

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
RUN uv pip install --system --no-cache .

# Docling caches its layout/OCR models under ~/.cache/docling.
# Operators mount a named volume at this path so models survive
# container restarts.
ENV HOME=/root
VOLUME ["/root/.cache/docling"]

CMD ["python", "-m", "worker_pdf.worker"]
