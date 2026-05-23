"""Tool registry for the FastMCP server.

Each module in this package exposes a `register(mcp)` function that
attaches its tools to the FastMCP instance. The server's
`__main__` imports them conditionally based on `config.modules.*`
flags so optional modules can be flipped on or off without code edits.
"""
