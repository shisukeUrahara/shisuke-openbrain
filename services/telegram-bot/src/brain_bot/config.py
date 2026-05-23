"""Telegram bot configuration.

Reads env vars + the project-wide config/features.yaml. Exposes a
frozen Config object so the rest of the codebase never reaches into
os.environ.
"""
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
    bot_token: str
    owner_id: int
    brain_url: str
    redis_url: str


def _env_bool(name: str, fallback: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return fallback
    return raw.strip().lower() in _TRUE_VALUES


def _yaml_flag(yaml_path: Path) -> bool:
    """Read modules.telegram_bot.enabled from the project features.yaml.
    Missing file or missing key both resolve to False."""
    if not yaml_path.exists():
        return False
    data = yaml.safe_load(yaml_path.read_text()) or {}
    node: Any = data.get("modules", {}).get("telegram_bot", {})
    if not isinstance(node, dict):
        return False
    return bool(node.get("enabled", False))


def load_config(
    yaml_path: str | Path = "config/features.yaml",
    *,
    require_runtime: bool = True,
) -> Config:
    """Load the bot's Config.

    `require_runtime=False` is for unit tests that only care about the
    flag-resolution path — it skips the bot-token / owner-id checks.
    """
    enabled = _env_bool(
        "MODULE_TELEGRAM_BOT_ENABLED", _yaml_flag(Path(yaml_path))
    )

    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    owner_raw = os.environ.get("TELEGRAM_OWNER_ID", "")
    brain_url = os.environ.get("BRAIN_URL", "")
    redis_url = os.environ.get("REDIS_URL", "redis://redis:6379/0")

    if enabled and require_runtime:
        missing = []
        if not bot_token:
            missing.append("TELEGRAM_BOT_TOKEN")
        if not owner_raw:
            missing.append("TELEGRAM_OWNER_ID")
        if not brain_url:
            missing.append("BRAIN_URL")
        if missing:
            raise RuntimeError(
                "telegram bot module is enabled but missing required env vars: "
                + ", ".join(missing)
            )

    owner_id = int(owner_raw) if owner_raw else 0

    return Config(
        enabled=enabled,
        bot_token=bot_token,
        owner_id=owner_id,
        brain_url=brain_url,
        redis_url=redis_url,
    )
