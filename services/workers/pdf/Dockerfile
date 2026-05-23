FROM python:3.12-slim AS base

# pymupdf ships a self-contained C extension so we do not need
# libgomp / libgl / libglib like the Docling variant did. Only
# ca-certificates for httpx TLS.
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates \
 && rm -rf /var/lib/apt/lists/* \
 && pip install --no-cache-dir uv

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
RUN uv pip install --system --no-cache .

# No persistent cache to mount — pymupdf has no model downloads.

CMD ["python", "-m", "worker_pdf.worker"]
