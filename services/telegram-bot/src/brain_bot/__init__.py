"""brain_bot — Telegram capture bot for the self-hosted Open Brain.

The package splits cleanly so unit tests never need a real Bot or a
live Telegram update:

- handlers.py is pure: it classifies a normalized message into a
  typed Action with no I/O.
- mcp_client / queue_client are thin wrappers around httpx and redis
  that side-effect the world.
- server.py glues aiogram to the above and starts the polling loop.
"""

__version__ = "0.1.0"
