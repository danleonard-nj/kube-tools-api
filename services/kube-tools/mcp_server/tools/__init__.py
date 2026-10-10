"""MCP tool surface over the journal services, one module per area.

Mostly read-only. The write tools (create_entry, set_title, update_tags) add
entries and change titles and tags only, and require the write scope. Nothing
deletes, edits transcripts, polishes or reprocesses.
"""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from mcp_server.tools import entries, stats, tags
from mcp_server.tools.common import ToolRunner
from models.mcp_config import McpConfig

_MODULES = (entries, stats, tags)


def register_tools(server: MCPServer, config: McpConfig) -> None:
    """Attach every tool to the MCP server."""
    runner = ToolRunner(config)
    for module in _MODULES:
        module.register(server, runner)
