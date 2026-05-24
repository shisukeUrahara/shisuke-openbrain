"""Obsidian-sync configuration."""
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
    database_url: str
    vault_dir: str
    backfill_on_start: bool


def _env_bool(name: str, fallback: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return fallback
    return raw.strip().lower() in _TRUE_VALUES


def _yaml_flag(yaml_path: Path) -> bool:
    if not yaml_path.exists():
        return False
    data = yaml.safe_load(yaml_path.read_text()) or {}
    node: Any = data.get("modules", {}).get("obsidian_mirror", {})
    if not isinstance(node, dict):
        return False
    return bool(node.get("enabled", False))


def load_config(
    yaml_path: str | Path = "config/features.yaml",
    *,
    require_runtime: bool = True,
) -> Config:
    enabled = _env_bool("MODULE_OBSIDIAN_MIRROR_ENABLED", _yaml_flag(Path(yaml_path)))
    database_url = os.environ.get("DATABASE_URL", "")
    vault_dir = os.environ.get("VAULT_DIR", "/vault")
    backfill = _env_bool("VAULT_BACKFILL_ON_START", True)

    if enabled and require_runtime and not database_url:
        raise RuntimeError(
            "obsidian mirror module is enabled but DATABASE_URL is not set"
        )

    return Config(
        enabled=enabled,
        database_url=database_url,
        vault_dir=vault_dir,
        backfill_on_start=backfill,
    )
