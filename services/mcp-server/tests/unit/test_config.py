"""Unit tests for the configuration loader.

Layer: unit
Phase: 02
Run:   pytest services/mcp-server/tests/unit/test_config.py -v
"""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    """Strip every env var the loader reads so each test starts from a
    known empty environment."""
    for key in (
        "DATABASE_URL",
        "BRAIN_KEY",
        "EMBED_PROVIDER",
        "OPENROUTER_API_KEY",
        "OLLAMA_URL",
        "MODULE_DOCUMENTS_ENABLED",
        "MODULE_TELEGRAM_BOT_ENABLED",
        "MODULE_WORKERS_ARTICLE_ENABLED",
        "MODULE_WORKERS_PDF_ENABLED",
        "MODULE_WORKERS_AUDIO_ENABLED",
        "MODULE_WORKERS_IMAGE_ENABLED",
        "MODULE_OBSIDIAN_MIRROR_ENABLED",
        "MODULE_N8N_SCHEDULER_ENABLED",
        "MODULE_GRAPHIFY_ENABLED",
    ):
        monkeypatch.delenv(key, raising=False)
    return monkeypatch


@pytest.fixture
def yaml_all_disabled(tmp_path: Path) -> Path:
    """A features.yaml mirroring the project default — every module off."""
    path = tmp_path / "features.yaml"
    path.write_text(textwrap.dedent("""\
        version: 1
        modules:
          documents:        {enabled: false}
          telegram_bot:     {enabled: false}
          workers:
            article:        {enabled: false}
            pdf:            {enabled: false}
            audio:          {enabled: false}
            image:          {enabled: false}
          obsidian_mirror:  {enabled: false}
          n8n_scheduler:    {enabled: false}
          graphify:         {enabled: false}
    """))
    return path


# ──────────────────────────────────────────────────────────────────
# Defaults: empty env + missing yaml
# ──────────────────────────────────────────────────────────────────

def test_load_config_works_without_yaml_file(clean_env, tmp_path):
    """Missing features.yaml is not an error; all flags fall back to False."""
    from brain_mcp.config import load_config

    cfg = load_config(yaml_path=tmp_path / "no-such.yaml", require_secrets=False)
    assert cfg.modules.documents is False
    assert cfg.modules.telegram_bot is False
    assert cfg.modules.workers_article is False
    assert cfg.modules.workers_pdf is False
    assert cfg.modules.workers_audio is False
    assert cfg.modules.workers_image is False
    assert cfg.modules.obsidian_mirror is False
    assert cfg.modules.n8n_scheduler is False
    assert cfg.modules.graphify is False


def test_default_embed_provider_is_openrouter(clean_env, yaml_all_disabled):
    from brain_mcp.config import load_config
    cfg = load_config(yaml_path=yaml_all_disabled, require_secrets=False)
    assert cfg.embed_provider == "openrouter"


def test_default_ollama_url_set(clean_env, yaml_all_disabled):
    from brain_mcp.config import load_config
    cfg = load_config(yaml_path=yaml_all_disabled, require_secrets=False)
    assert cfg.ollama_url == "http://ollama:11434"


# ──────────────────────────────────────────────────────────────────
# Env overrides yaml
# ──────────────────────────────────────────────────────────────────

def test_env_flag_true_overrides_yaml_false(clean_env, yaml_all_disabled):
    from brain_mcp.config import load_config

    clean_env.setenv("MODULE_DOCUMENTS_ENABLED", "true")
    cfg = load_config(yaml_path=yaml_all_disabled, require_secrets=False)
    assert cfg.modules.documents is True


def test_env_flag_accepts_multiple_truthy_values(clean_env, yaml_all_disabled, monkeypatch):
    """1 / true / yes / on (any case) all mean enabled."""
    from brain_mcp.config import load_config

    for value in ("1", "true", "TRUE", "yes", "Yes", "on"):
        monkeypatch.setenv("MODULE_TELEGRAM_BOT_ENABLED", value)
        cfg = load_config(yaml_path=yaml_all_disabled, require_secrets=False)
        assert cfg.modules.telegram_bot is True, f"expected True for value={value!r}"


def test_env_flag_falsy_value_yields_false(clean_env, yaml_all_disabled):
    from brain_mcp.config import load_config
    clean_env.setenv("MODULE_DOCUMENTS_ENABLED", "false")
    cfg = load_config(yaml_path=yaml_all_disabled, require_secrets=False)
    assert cfg.modules.documents is False


def test_yaml_flag_true_picks_up_when_env_unset(clean_env, tmp_path):
    """Falling back to yaml when env is absent."""
    from brain_mcp.config import load_config

    path = tmp_path / "features.yaml"
    path.write_text(textwrap.dedent("""\
        modules:
          documents: {enabled: true}
          workers:
            pdf: {enabled: true}
    """))
    cfg = load_config(yaml_path=path, require_secrets=False)
    assert cfg.modules.documents is True
    assert cfg.modules.workers_pdf is True
    assert cfg.modules.telegram_bot is False  # unchanged


def test_nested_workers_flag_resolves_through_dotted_path(clean_env, yaml_all_disabled):
    """The nested workers.article flag resolves via env override."""
    from brain_mcp.config import load_config

    clean_env.setenv("MODULE_WORKERS_ARTICLE_ENABLED", "true")
    cfg = load_config(yaml_path=yaml_all_disabled, require_secrets=False)
    assert cfg.modules.workers_article is True
    assert cfg.modules.workers_pdf is False


# ──────────────────────────────────────────────────────────────────
# Required secrets enforcement
# ──────────────────────────────────────────────────────────────────

def test_missing_required_brain_key_raises(clean_env, yaml_all_disabled):
    from brain_mcp.config import load_config

    clean_env.setenv("DATABASE_URL", "postgresql://test/test")
    with pytest.raises(RuntimeError, match="BRAIN_KEY"):
        load_config(yaml_path=yaml_all_disabled, require_secrets=True)


def test_missing_required_database_url_raises(clean_env, yaml_all_disabled):
    from brain_mcp.config import load_config

    clean_env.setenv("BRAIN_KEY", "abc" * 16)
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        load_config(yaml_path=yaml_all_disabled, require_secrets=True)


def test_secrets_pulled_through_when_present(clean_env, yaml_all_disabled):
    from brain_mcp.config import load_config

    clean_env.setenv("DATABASE_URL", "postgresql://u:p@h/db")
    clean_env.setenv("BRAIN_KEY", "a" * 64)
    clean_env.setenv("OPENROUTER_API_KEY", "sk-or-test")
    cfg = load_config(yaml_path=yaml_all_disabled, require_secrets=True)
    assert cfg.database_url == "postgresql://u:p@h/db"
    assert cfg.brain_key == "a" * 64
    assert cfg.openrouter_api_key == "sk-or-test"


# ──────────────────────────────────────────────────────────────────
# as_dict surface for /health
# ──────────────────────────────────────────────────────────────────

def test_modules_as_dict_lists_every_flag(clean_env, yaml_all_disabled):
    from brain_mcp.config import load_config

    cfg = load_config(yaml_path=yaml_all_disabled, require_secrets=False)
    keys = set(cfg.modules.as_dict().keys())
    assert keys == {
        "documents",
        "telegram_bot",
        "workers_article",
        "workers_pdf",
        "workers_audio",
        "workers_image",
        "obsidian_mirror",
        "n8n_scheduler",
        "graphify",
    }


def test_modules_as_dict_reflects_overrides(clean_env, yaml_all_disabled):
    from brain_mcp.config import load_config

    clean_env.setenv("MODULE_DOCUMENTS_ENABLED", "true")
    clean_env.setenv("MODULE_GRAPHIFY_ENABLED", "yes")
    cfg = load_config(yaml_path=yaml_all_disabled, require_secrets=False)
    d = cfg.modules.as_dict()
    assert d["documents"] is True
    assert d["graphify"] is True
    assert d["telegram_bot"] is False
