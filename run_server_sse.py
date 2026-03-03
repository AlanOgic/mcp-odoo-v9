#!/usr/bin/env python3
"""
Run the Odoo v9 MCP server with SSE (Server-Sent Events) transport.

SSE transport enables web browsers and HTTP clients to connect to the MCP server
via Server-Sent Events, providing real-time streaming capabilities over HTTP.

Environment Variables:
    MCP_HOST: Host to bind to (default: 127.0.0.1)
    MCP_PORT: Port to listen on (default: 8009)
    MCP_SSE_PATH: SSE endpoint path (default: /sse)
    ODOO_URL: Odoo server URL
    ODOO_DB: Database name
    ODOO_USERNAME: Login username
    ODOO_PASSWORD: Login password
    ODOO_TIMEOUT: Connection timeout in seconds (default: 30)
    ODOO_VERIFY_SSL: Whether to verify SSL certificates (default: true)
    HTTP_PROXY: HTTP proxy for Odoo connection (optional)

Usage:
    python run_server_sse.py

    # With custom host/port
    MCP_HOST=localhost MCP_PORT=9000 python run_server_sse.py

    # Docker
    docker run -p 8009:8009 alanogic/mcp-odoo-v9:sse
"""

import os
import sys

from odoo_mcp.logging_utils import setup_tee_logging

setup_tee_logging("sse")

from odoo_mcp.server import mcp  # noqa: E402 — logging must be set up before this import

# Get SSE configuration from environment
host = os.environ.get("MCP_HOST", "127.0.0.1")
port = int(os.environ.get("MCP_PORT", "8009"))
path = os.environ.get("MCP_SSE_PATH", "/sse")

if host == "0.0.0.0":
    print(
        "WARNING: MCP server binding to 0.0.0.0 (all interfaces). "
        "Ensure a reverse proxy with authentication is in place. "
        "Set MCP_HOST=127.0.0.1 for local-only access.",
        file=sys.stderr,
    )

print("SSE Configuration:")
print(f"  Host: {host}")
print(f"  Port: {port}")
print(f"  SSE Path: {path}")
print(f"  URL: http://{host}:{port}{path}")

# Run with SSE transport
mcp.run(
    transport="sse",
    host=host,
    port=port,
    path=path,
)
