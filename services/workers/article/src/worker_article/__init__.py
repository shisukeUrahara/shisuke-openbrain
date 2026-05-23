"""worker_article — article ingestion worker.

Module layout, in dependency order so importing this package brings
nothing accidental:

  config.py    -> env + features.yaml loader (no I/O at import time)
  chunker.py   -> pure markdown chunker (no I/O at all)
  fetcher.py   -> trafilatura wrapper (network on call)
  mcp_client.py-> httpx wrapper for capture_document + add_chunks
  queue.py     -> redis BRPOP wrapper
  worker.py    -> the main() loop
"""

__version__ = "0.1.0"
