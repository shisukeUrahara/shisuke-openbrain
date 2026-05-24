FROM python:3.12-slim AS base

RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates \
 && rm -rf /var/lib/apt/lists/* \
 && pip install --no-cache-dir uv

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
RUN uv pip install --system --no-cache .

# The vault is a mounted volume; declare it so intent is clear.
VOLUME ["/vault"]

CMD ["python", "-m", "obsidian_sync.main"]
