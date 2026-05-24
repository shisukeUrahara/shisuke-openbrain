"""Integration tests for export_project_corpus (graphify module).

Layer: integration
Phase: 15
Run:   pytest services/mcp-server/tests/integration/test_tools_graphify.py -v
"""
from __future__ import annotations

from pathlib import Path

import psycopg
import pytest
import pytest_asyncio
from fastmcp import FastMCP

from brain_mcp.tools import graphify_export


REPO_ROOT = Path(__file__).resolve().parents[4]
DOCS_DIR = REPO_ROOT / "sql" / "modules" / "documents"


@pytest.fixture
def graphify_pg(pg: str):
    """Documents module applied + tables truncated."""
    with psycopg.connect(pg, autocommit=True) as conn:
        for fname in ("010_documents.sql", "011_chunks.sql", "012_match_chunks.sql"):
            conn.execute((DOCS_DIR / fname).read_text())
        conn.execute("DELETE FROM chunks WHERE TRUE")
        conn.execute("DELETE FROM documents WHERE TRUE")
        conn.execute("DELETE FROM thoughts WHERE TRUE")
    return pg


@pytest_asyncio.fixture
async def mcp_graphify(graphify_pg, config, pool):
    mcp = FastMCP(name="test-graphify")
    graphify_export.register(mcp, config=config)
    return mcp


async def _call(mcp: FastMCP, name: str, args: dict):
    tool = await mcp.get_tool(name)
    return await tool.fn(**args)


async def test_export_empty_project_creates_dir_with_zero_counts(mcp_graphify, tmp_path):
    result = await _call(
        mcp_graphify, "export_project_corpus",
        {"project": "ghost", "out_dir": str(tmp_path)},
    )
    assert result["documents"] == 0
    assert result["thoughts"] == 0
    assert Path(result["out_dir"]).is_dir()


async def test_export_writes_document_files(graphify_pg, mcp_graphify, tmp_path):
    with psycopg.connect(graphify_pg, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO documents (title, kind, source, content_md, project) "
            "VALUES ('Alpha Doc', 'article', 'https://a', 'alpha body', 'ax'), "
            "       ('Beta Doc', 'pdf', 'https://b', 'beta body', 'ax'), "
            "       ('Other', 'article', 'https://c', 'other', 'zz')"
        )

    result = await _call(
        mcp_graphify, "export_project_corpus",
        {"project": "ax", "out_dir": str(tmp_path)},
    )
    assert result["documents"] == 2  # only ax-tagged

    out = Path(result["out_dir"])
    files = sorted(p.name for p in out.glob("*.md"))
    assert any("Alpha_Doc" in f for f in files)
    assert any("Beta_Doc" in f for f in files)
    assert not any("Other" in f for f in files)

    alpha = next(out.glob("*Alpha_Doc*.md")).read_text()
    assert "# Alpha Doc" in alpha
    assert "alpha body" in alpha
    assert "source: https://a" in alpha


async def test_export_writes_aggregated_thoughts(graphify_pg, mcp_graphify, tmp_path):
    with psycopg.connect(graphify_pg, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO thoughts (content, metadata) VALUES "
            "('thought one', '{\"project\": \"ax\", \"type\": \"idea\"}'::jsonb), "
            "('thought two', '{\"project\": \"ax\"}'::jsonb), "
            "('off topic', '{\"project\": \"zz\"}'::jsonb)"
        )
    result = await _call(
        mcp_graphify, "export_project_corpus",
        {"project": "ax", "out_dir": str(tmp_path)},
    )
    assert result["thoughts"] == 2

    agg = (Path(result["out_dir"]) / "_thoughts.md").read_text()
    assert "thought one" in agg
    assert "thought two" in agg
    assert "off topic" not in agg
    assert "[idea]" in agg  # metadata.type rendered


async def test_export_rejects_empty_project(mcp_graphify, tmp_path):
    with pytest.raises(ValueError, match="project"):
        await _call(
            mcp_graphify, "export_project_corpus",
            {"project": "  ", "out_dir": str(tmp_path)},
        )


async def test_export_sanitises_project_name_for_path(mcp_graphify, tmp_path):
    """A project name with slashes must not escape out_dir."""
    result = await _call(
        mcp_graphify, "export_project_corpus",
        {"project": "../../etc", "out_dir": str(tmp_path)},
    )
    out = Path(result["out_dir"])
    # The resolved path stays under tmp_path.
    assert str(out).startswith(str(tmp_path.resolve()))
    assert ".." not in out.name


async def test_export_works_without_documents_table(pg, config, pool, tmp_path):
    """A thoughts-only brain (documents module never enabled) should
    still export thoughts without erroring on the missing table."""
    # Use the base `pg` (no documents migrations applied).
    with psycopg.connect(pg, autocommit=True) as conn:
        conn.execute("DELETE FROM thoughts WHERE TRUE")
        conn.execute(
            "INSERT INTO thoughts (content, metadata) VALUES "
            "('solo thought', '{\"project\": \"solo\"}'::jsonb)"
        )
    mcp = FastMCP(name="test-graphify-nodocs")
    graphify_export.register(mcp, config=config)
    result = await _call(
        mcp, "export_project_corpus",
        {"project": "solo", "out_dir": str(tmp_path)},
    )
    assert result["documents"] == 0
    assert result["thoughts"] == 1
