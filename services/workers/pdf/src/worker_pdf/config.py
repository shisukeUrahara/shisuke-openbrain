"""PDF worker configuration."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


_TRUE_VALUES = {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Config:
    enabled: bool
    brain_url: str
    redis_url: str
    queue: str
    max_pdf_bytes: int
    max_chunk_tokens: int
    chunk_overlap_tokens: int


def _env_bool(name: str, fallback: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return fallback
    return raw.strip().lower() in _TRUE_VALUES


def _yaml_flag(yaml_path: Path) -> bool:
    if not yaml_path.exists():
        return False
    data = yaml.safe_load(yaml_path.read_text()) or {}
    node: Any = data.get("modules", {}).get("workers", {}).get("pdf", {})
    if not isinstance(node, dict):
        return False
    return bool(node.get("enabled", False))


def load_config(
    yaml_path: str | Path = "config/features.yaml",
    *,
    require_runtime: bool = True,
) -> Config:
    enabled = _env_bool("MODULE_WORKERS_PDF_ENABLED", _yaml_flag(Path(yaml_path)))
    brain_url = os.environ.get("BRAIN_URL", "")
    redis_url = os.environ.get("REDIS_URL", "redis://redis:6379/0")
    queue = os.environ.get("WORKER_QUEUE", "ingest:pdf")
    # 20 MB default matches the Telegram Bot API download cap.
    max_pdf_bytes = int(os.environ.get("WORKER_MAX_PDF_BYTES", str(20 * 1024 * 1024)))
    max_chunk = int(os.environ.get("WORKER_MAX_CHUNK_TOKENS", "800"))
    chunk_overlap = int(os.environ.get("WORKER_CHUNK_OVERLAP_TOKENS", "120"))

    if enabled and require_runtime:
        missing = []
        if not brain_url:
            missing.append("BRAIN_URL")
        if not redis_url:
            missing.append("REDIS_URL")
        if missing:
            raise RuntimeError(
                "pdf worker module is enabled but missing required env vars: "
                + ", ".join(missing)
            )

    return Config(
        enabled=enabled,
        brain_url=brain_url,
        redis_url=redis_url,
        queue=queue,
        max_pdf_bytes=max_pdf_bytes,
        max_chunk_tokens=max_chunk,
        chunk_overlap_tokens=chunk_overlap,
    )
