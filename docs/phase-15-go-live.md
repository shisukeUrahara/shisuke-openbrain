# Phase 15 — Graphify Export Go-Live (Operator Guide)

Graphify is a **batch synthesis** step, not part of the live spine. The
brain keeps capturing thoughts and documents continuously; graphify is
something you run *on demand* over a slice of that corpus to produce a
knowledge graph + report, then capture the findings back as synthesis
thoughts.

The MCP server owns one seam in this loop: `export_project_corpus`. It
dumps every document and thought tagged with a project into a folder of
markdown files that graphify (running on the host) can ingest.

```
  brain (Postgres)
       │  export_project_corpus(project)
       ▼
  /exports/<project>/            ← volume-mounted, host-readable
    ├── article__Title.md        ← one file per document (kind__title)
    └── _thoughts.md             ← all matching thoughts, aggregated
       │  graphify (host tool, run manually)
       ▼
  knowledge graph + report
       │  capture(...) the findings
       ▼
  back into the brain — the loop compounds
```

Unlike the capture tools, **export touches no embedding provider** — it
only reads content columns and writes files. So it works without an
`OPENROUTER_API_KEY`.

## Step 1 — Enable

```bash
grep -q '^MODULE_GRAPHIFY_ENABLED=' .env \
  && sed -i 's|^MODULE_GRAPHIFY_ENABLED=.*$|MODULE_GRAPHIFY_ENABLED=true|' .env \
  || echo 'MODULE_GRAPHIFY_ENABLED=true' >> .env

docker compose up -d --build mcp-server
```

Confirm the flag and the tool surface:

```bash
set -a; source .env; set +a
curl -s http://localhost:8080/health | jq '.modules.graphify'   # -> true

curl -s -X POST http://localhost:8080/mcp \
  -H "x-brain-key: $BRAIN_KEY" \
  -H 'Content-Type: application/json' -H 'Accept: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' \
  | jq -r '.result.tools[].name'      # includes export_project_corpus
```

## Step 2 — The exports volume

`docker-compose.yml` mounts a named volume `exports` at `/exports`
inside the mcp-server. That is the default `out_dir`. To read the files
from your host, either:

- **inspect the named volume directly** —
  `docker compose exec mcp-server ls /exports/<project>`, or
- **bind-mount a host path instead** so graphify can read it natively.
  In `docker-compose.yml`, swap the `exports:/exports` line for a host
  bind such as `./exports:/exports`, then `docker compose up -d`.

The host bind is the right choice once you actually run graphify, since
graphify lives on the host, not in the container.

## Step 3 — Run an export

Call the tool from any connected MCP client (Claude Desktop, etc.) or
over HTTP:

```bash
curl -s -X POST http://localhost:8080/mcp \
  -H "x-brain-key: $BRAIN_KEY" \
  -H 'Content-Type: application/json' -H 'Accept: application/json' \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{
        "name":"export_project_corpus",
        "arguments":{"project":"my-research"}}}' \
  | jq -r '.result.content[0].text | fromjson'
# -> {"out_dir":"/exports/my-research","documents":12,"thoughts":47}
```

What counts as "tagged with the project":

- **documents** — `documents.project = '<project>'`.
- **thoughts** — `metadata->>'project'` equals the project, **or** the
  project appears in a `metadata.projects` array. So a thought can
  belong to several projects.

Output layout under `/exports/<project>/`:

- one `<kind>__<title>.md` per document (frontmatter-light header +
  `content_md` body),
- a single `_thoughts.md` aggregating every matching thought, one line
  each: `(date) [type] content`.

If the documents module is disabled, export still runs and emits a
thoughts-only folder — the documents query is guarded with
`to_regclass`.

## Step 4 — Run graphify, capture findings back

This part runs on the host with your graphify tooling of choice, pointed
at `/exports/<project>/` (or the host-bind path). When it produces a
synthesis (themes, clusters, a summary), capture each finding back into
the brain so it becomes searchable and part of the next export:

```bash
curl -s -X POST http://localhost:8080/mcp \
  -H "x-brain-key: $BRAIN_KEY" \
  -H 'Content-Type: application/json' -H 'Accept: application/json' \
  -d '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{
        "name":"capture",
        "arguments":{"content":"<synthesis finding>",
                     "metadata":{"project":"my-research","type":"synthesis"}}}}'
```

Tag the synthesis with the same `project` and a `type: synthesis` so the
next export picks it up and you can distinguish raw notes from distilled
ones.

## Safety

`project` is user-controlled and becomes a path segment, so it is
sanitised to a single safe segment (`_safe_name`): whitespace collapses
to underscores first, then characters outside `[A-Za-z0-9._ -]` are
stripped, and the resolved target is re-asserted to stay inside
`out_dir` (`refusing to write outside out_dir`). A project name like
`../../etc` cannot escape the export folder.

## Configuration

| Env var | Default | Purpose |
|---|---|---|
| `MODULE_GRAPHIFY_ENABLED` | false | Master flag for the export tool |
| `out_dir` (tool arg) | `/exports` | Where files are written; must be inside the container's mounted volume |

## Troubleshooting

| Symptom | Fix |
|---|---|
| `tools/list` has no `export_project_corpus` | `MODULE_GRAPHIFY_ENABLED` is false, or the server wasn't rebuilt/recreated after the flag flip. |
| Export returns `{"documents":0}` but you have docs | The documents module is off, or none carry `project = '<project>'`. Confirm with `psql ... "select count(*) from documents where project='<project>'"`. |
| Export returns `{"thoughts":0}` | Your thoughts use a different `metadata` key. Export reads `metadata->>'project'` and `metadata.projects[]` only. |
| Can't find the files on the host | They're in the named `exports` volume, not a host folder. Either `docker compose exec mcp-server ls /exports` or switch to a host bind (Step 2). |
| `refusing to write outside out_dir` error | The project name sanitised to something that escaped the base — by design. Use a normal project name. |

## Notes

- Export is **read-only against the brain** — it never mutates
  `thoughts`/`documents`. Safe to run as often as you like.
- It is idempotent per run: re-exporting overwrites the project folder's
  files with current content.
- This closes the module phases (10–15). The remaining phases are
  deployment (VPS + reverse proxy + backups), which run once development
  is complete.
