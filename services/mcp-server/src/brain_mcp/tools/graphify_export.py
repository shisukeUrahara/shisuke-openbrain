"""MCP tool: export_project_corpus — dump a project slice to markdown.

Graphify is a batch synthesis tool that reads a folder of markdown
and produces a knowledge graph + report. It is NOT part of the live
spine — it runs on demand. This tool is the seam: it exports every
thought and document tagged with a given project into a folder of
markdown files that graphify can ingest, then the operator runs
graphify over that folder and captures the findings back as
synthesis thoughts.

Behind MODULE_GRAPHIFY_ENABLED. Writes into out_dir (a volume-mounted
path in the container, default /exports) so the host — and graphify
running on the host — can read the result.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from fastmcp import FastMCP

from ..config import Config
from ..db import conn


_UNSAFE = re.compile(r"[^A-Za-z0-9._ -]")
_WHITESPACE = re.compile(r"\s+")


def _safe_name(value: str | None, fallback: str) -> str:
    if not value or not value.strip():
        return fallback
    # Collapse whitespace to underscores first so filenames are
    # shell- and Obsidian-friendly, then strip unsafe characters.
    cleaned = _WHITESPACE.sub("_", value.strip())
    cleaned = _UNSAFE.sub("", cleaned).strip("._-")[:60].strip("._-")
    return cleaned or fallback


def register(mcp: FastMCP, *, config: Config) -> None:
    @mcp.tool
    async def export_project_corpus(
        project: str,
        out_dir: str = "/exports",
    ) -> dict[str, Any]:
        """Export every document and thought tagged with a project to a
        folder of markdown files, ready for graphify to ingest.

        Writes one markdown file per document plus a single aggregated
        _thoughts.md. Returns {out_dir, documents, thoughts} counts.
        The output path is guarded against traversal — `project` is
        sanitised to a single path segment.
        """
        if not project or not project.strip():
            raise ValueError("project must be a non-empty string")

        base = Path(out_dir).resolve()
        safe_project = _safe_name(project, fallback="project")
        target = (base / safe_project).resolve()
        if not str(target).startswith(str(base) + "/") and target != base / safe_project:
            raise ValueError("refusing to write outside out_dir")
        target.mkdir(parents=True, exist_ok=True)

        documents_written = 0
        thoughts_written = 0

        async with conn() as connection:
            # documents table only exists when the documents module is
            # enabled; guard the query so graphify can still export a
            # thoughts-only brain.
            has_documents = await connection.fetchval(
                "SELECT to_regclass('public.documents') IS NOT NULL"
            )
            if has_documents:
                docs = await connection.fetch(
                    "SELECT id, title, kind, source, content_md, created_at "
                    "FROM documents WHERE project = $1 ORDER BY created_at",
                    project,
                )
                for doc in docs:
                    fname = (
                        f"{_safe_name(doc['kind'], 'doc')}__"
                        f"{_safe_name(doc['title'], str(doc['id'])[:8])}.md"
                    )
                    body = (
                        f"# {doc['title']}\n\n"
                        f"- kind: {doc['kind']}\n"
                        f"- source: {doc['source'] or ''}\n"
                        f"- created: {doc['created_at'].isoformat()}\n\n"
                        f"{doc['content_md'] or ''}\n"
                    )
                    (target / fname).write_text(body, encoding="utf-8")
                    documents_written += 1

            thoughts = await connection.fetch(
                "SELECT content, metadata, created_at FROM thoughts "
                "WHERE metadata ->> 'project' = $1 OR $1 = ANY (CASE "
                "  WHEN jsonb_typeof(metadata -> 'projects') = 'array' "
                "  THEN ARRAY(SELECT jsonb_array_elements_text(metadata -> 'projects')) "
                "  ELSE ARRAY[]::text[] END) "
                "ORDER BY created_at",
                project,
            )
            if thoughts:
                lines = [f"# Thoughts — project: {project}\n"]
                for t in thoughts:
                    md_type = ""
                    metadata = t["metadata"]
                    # asyncpg returns jsonb as a string unless a codec
                    # is registered; parse defensively.
                    if isinstance(metadata, str):
                        try:
                            metadata = json.loads(metadata)
                        except (ValueError, TypeError):
                            metadata = {}
                    if isinstance(metadata, dict):
                        md_type = metadata.get("type", "")
                    lines.append(
                        f"- ({t['created_at'].date()}) "
                        f"{('[' + md_type + '] ') if md_type else ''}{t['content']}"
                    )
                (target / "_thoughts.md").write_text(
                    "\n".join(lines) + "\n", encoding="utf-8"
                )
                thoughts_written = len(thoughts)

        return {
            "out_dir": str(target),
            "documents": documents_written,
            "thoughts": thoughts_written,
        }
