FROM python:3.12-slim AS base

RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates \
 && rm -rf /var/lib/apt/lists/* \
 && pip install --no-cache-dir uv

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
RUN uv pip install --system --no-cache .

# No exposed port — the bot is an outbound poller.

CMD ["python", "-m", "brain_bot.server"]
