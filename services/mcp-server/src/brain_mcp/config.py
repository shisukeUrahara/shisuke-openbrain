"""Configuration loader.

Resolution order (highest priority first):
    1. Environment variables (MODULE_*_ENABLED, DATABASE_URL, etc.)
    2. config/features.yaml in the project root
    3. Built-in defaults defined here

All values are exposed as a frozen `Config` object. The whole point of
loading once is so the rest of the codebase never reaches into
`os.environ` directly — that path leaks surprise defaults and makes
tests harder to write.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


# ──────────────────────────────────────────────────────────────────
# Module flags
# ──────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Modules:
    documents: bool = False
    telegram_bot: bool = False
    workers_article: bool = False
    workers_pdf: bool = False
    workers_audio: bool = False
    workers_image: bool = False
    obsidian_mirror: bool = False
    n8n_scheduler: bool = False
    graphify: bool = False

    def as_dict(self) -> dict[str, bool]:
        """Surface the module set to /health as a plain dict."""
        return {
            "documents": self.documents,
            "telegram_bot": self.telegram_bot,
            "workers_article": self.workers_article,
            "workers_pdf": self.workers_pdf,
            "workers_audio": self.workers_audio,
            "workers_image": self.workers_image,
            "obsidian_mirror": self.obsidian_mirror,
            "n8n_scheduler": self.n8n_scheduler,
            "graphify": self.graphify,
        }


# ──────────────────────────────────────────────────────────────────
# Top-level config
# ──────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Config:
    database_url: str
    brain_key: str
    embed_provider: str
    openrouter_api_key: str | None
    ollama_url: str
    modules: Modules
    rate_limit_enabled: bool = True
    rate_limit_per_min: int = 100


# ──────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────

_TRUE_VALUES = {"1", "true", "yes", "on"}


def _env_bool(name: str, fallback: bool) -> bool:
    """Read a boolean env var; treat unset as `fallback`."""
    raw = os.environ.get(name)
    if raw is None:
        return fallback
    return raw.strip().lower() in _TRUE_VALUES


def _yaml_modules(yaml_path: Path) -> dict[str, Any]:
    """Read the modules block from features.yaml; tolerate missing file."""
    if not yaml_path.exists():
        return {}
    raw = yaml.safe_load(yaml_path.read_text()) or {}
    return raw.get("modules", {}) or {}


def _yaml_flag(modules: dict[str, Any], *path: str) -> bool:
    """Walk into the nested modules dict and read the `enabled` leaf."""
    node: Any = modules
    for key in path:
        if not isinstance(node, dict) or key not in node:
            return False
        node = node[key]
    if isinstance(node, dict):
        return bool(node.get("enabled", False))
    return False


def _require_env(name: str) -> str:
    """Pull a required env var or raise."""
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"required environment variable not set: {name}")
    return value


# ──────────────────────────────────────────────────────────────────
# Loader
# ──────────────────────────────────────────────────────────────────

def load_config(
    yaml_path: str | Path = "config/features.yaml",
    *,
    require_secrets: bool = True,
) -> Config:
    """Load Config from yaml + env.

    `require_secrets=False` lets tests construct a Config without
    setting BRAIN_KEY / DATABASE_URL — handy for unit testing the
    module-flag resolution path in isolation.
    """
    yaml_modules = _yaml_modules(Path(yaml_path))

    modules = Modules(
        documents=_env_bool(
            "MODULE_DOCUMENTS_ENABLED",
            _yaml_flag(yaml_modules, "documents"),
        ),
        telegram_bot=_env_bool(
            "MODULE_TELEGRAM_BOT_ENABLED",
            _yaml_flag(yaml_modules, "telegram_bot"),
        ),
        workers_article=_env_bool(
            "MODULE_WORKERS_ARTICLE_ENABLED",
            _yaml_flag(yaml_modules, "workers", "article"),
        ),
        workers_pdf=_env_bool(
            "MODULE_WORKERS_PDF_ENABLED",
            _yaml_flag(yaml_modules, "workers", "pdf"),
        ),
        workers_audio=_env_bool(
            "MODULE_WORKERS_AUDIO_ENABLED",
            _yaml_flag(yaml_modules, "workers", "audio"),
        ),
        workers_image=_env_bool(
            "MODULE_WORKERS_IMAGE_ENABLED",
            _yaml_flag(yaml_modules, "workers", "image"),
        ),
        obsidian_mirror=_env_bool(
            "MODULE_OBSIDIAN_MIRROR_ENABLED",
            _yaml_flag(yaml_modules, "obsidian_mirror"),
        ),
        n8n_scheduler=_env_bool(
            "MODULE_N8N_SCHEDULER_ENABLED",
            _yaml_flag(yaml_modules, "n8n_scheduler"),
        ),
        graphify=_env_bool(
            "MODULE_GRAPHIFY_ENABLED",
            _yaml_flag(yaml_modules, "graphify"),
        ),
    )

    if require_secrets:
        database_url = _require_env("DATABASE_URL")
        brain_key = _require_env("BRAIN_KEY")
    else:
        database_url = os.environ.get("DATABASE_URL", "")
        brain_key = os.environ.get("BRAIN_KEY", "")

    return Config(
        database_url=database_url,
        brain_key=brain_key,
        embed_provider=os.environ.get("EMBED_PROVIDER", "openrouter"),
        openrouter_api_key=os.environ.get("OPENROUTER_API_KEY"),
        ollama_url=os.environ.get("OLLAMA_URL", "http://ollama:11434"),
        modules=modules,
        rate_limit_enabled=_env_bool("RATE_LIMIT_ENABLED", True),
        rate_limit_per_min=int(os.environ.get("RATE_LIMIT_PER_MIN", "100")),
    )
