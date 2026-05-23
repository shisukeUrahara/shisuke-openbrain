"""Unit tests for brain_bot.config.

Layer: unit
Phase: 11
Run:   pytest services/telegram-bot/tests/unit/test_config.py -v
"""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch):
    for key in (
        "MODULE_TELEGRAM_BOT_ENABLED",
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_OWNER_ID",
        "BRAIN_URL",
        "REDIS_URL",
    ):
        monkeypatch.delenv(key, raising=False)
    return monkeypatch


@pytest.fixture
def yaml_disabled(tmp_path: Path) -> Path:
    p = tmp_path / "features.yaml"
    p.write_text(textwrap.dedent("""\
        modules:
          telegram_bot: {enabled: false}
    """))
    return p


@pytest.fixture
def yaml_enabled(tmp_path: Path) -> Path:
    p = tmp_path / "features.yaml"
    p.write_text(textwrap.dedent("""\
        modules:
          telegram_bot: {enabled: true}
    """))
    return p


def test_disabled_by_default_when_nothing_set(clean_env, tmp_path):
    from brain_bot.config import load_config
    cfg = load_config(yaml_path=tmp_path / "no-such.yaml", require_runtime=False)
    assert cfg.enabled is False


def test_env_flag_overrides_yaml_disabled(clean_env, yaml_disabled):
    from brain_bot.config import load_config
    clean_env.setenv("MODULE_TELEGRAM_BOT_ENABLED", "true")
    cfg = load_config(yaml_path=yaml_disabled, require_runtime=False)
    assert cfg.enabled is True


def test_yaml_enabled_picks_up_when_env_unset(clean_env, yaml_enabled):
    from brain_bot.config import load_config
    cfg = load_config(yaml_path=yaml_enabled, require_runtime=False)
    assert cfg.enabled is True


def test_runtime_missing_token_raises_when_enabled(clean_env, yaml_enabled):
    from brain_bot.config import load_config
    # No TELEGRAM_BOT_TOKEN, no TELEGRAM_OWNER_ID, no BRAIN_URL set.
    with pytest.raises(RuntimeError, match="TELEGRAM_BOT_TOKEN"):
        load_config(yaml_path=yaml_enabled, require_runtime=True)


def test_runtime_with_all_env_vars_passes(clean_env, yaml_enabled):
    from brain_bot.config import load_config
    clean_env.setenv("TELEGRAM_BOT_TOKEN", "tok")
    clean_env.setenv("TELEGRAM_OWNER_ID", "99")
    clean_env.setenv("BRAIN_URL", "http://mcp/mcp?key=xyz")
    cfg = load_config(yaml_path=yaml_enabled, require_runtime=True)
    assert cfg.bot_token == "tok"
    assert cfg.owner_id == 99
    assert cfg.brain_url == "http://mcp/mcp?key=xyz"


def test_default_redis_url_set(clean_env, yaml_disabled):
    from brain_bot.config import load_config
    cfg = load_config(yaml_path=yaml_disabled, require_runtime=False)
    assert cfg.redis_url == "redis://redis:6379/0"


def test_redis_url_override(clean_env, yaml_disabled):
    from brain_bot.config import load_config
    clean_env.setenv("REDIS_URL", "redis://other:1234/2")
    cfg = load_config(yaml_path=yaml_disabled, require_runtime=False)
    assert cfg.redis_url == "redis://other:1234/2"


def test_runtime_check_skipped_when_disabled(clean_env, yaml_disabled):
    """A disabled module must NOT enforce runtime env vars — the
    container should start cleanly in idle mode."""
    from brain_bot.config import load_config
    # Disabled, no other env set.
    cfg = load_config(yaml_path=yaml_disabled, require_runtime=True)
    assert cfg.enabled is False
    assert cfg.bot_token == ""
