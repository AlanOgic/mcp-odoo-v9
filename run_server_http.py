#!/usr/bin/env python3
"""
Run the Odoo v9 MCP server with Streamable HTTP transport.

Streamable HTTP transport enables bidirectional streaming over HTTP/2,
suitable for API clients and programmatic integrations.

Environment Variables:
    MCP_HOST: Host to bind to (default: 127.0.0.1)
    MCP_PORT: Port to listen on (default: 8008)
    MCP_HTTP_PATH: HTTP endpoint path (default: /mcp)
    ODOO_URL: Odoo server URL
    ODOO_DB: Database name
    ODOO_USERNAME: Login username
    ODOO_PASSWORD: Login password
    ODOO_TIMEOUT: Connection timeout in seconds (default: 30)
    ODOO_VERIFY_SSL: Whether to verify SSL certificates (default: true)
    HTTP_PROXY: HTTP proxy for Odoo connection (optional)

Usage:
    python run_server_http.py

    # With custom host/port
    MCP_HOST=localhost MCP_PORT=9000 python run_server_http.py

    # Docker
    docker run -p 8008:8008 alanogic/mcp-odoo-v9:http
"""

import os
import sys

from odoo_mcp.logging_utils import setup_tee_logging

setup_tee_logging("http")

from odoo_mcp.server import mcp  # noqa: E402 — logging must be set up before this import

# Get HTTP configuration from environment
host = os.environ.get("MCP_HOST", "127.0.0.1")
port = int(os.environ.get("MCP_PORT", "8008"))
path = os.environ.get("MCP_HTTP_PATH", "/mcp")

if host == "0.0.0.0":
    print(
        "WARNING: MCP server binding to 0.0.0.0 (all interfaces). "
        "Ensure a reverse proxy with authentication is in place. "
        "Set MCP_HOST=127.0.0.1 for local-only access.",
        file=sys.stderr,
    )

print("Streamable HTTP Configuration:")
print(f"  Host: {host}")
print(f"  Port: {port}")
print(f"  HTTP Path: {path}")
print(f"  URL: http://{host}:{port}{path}")

# Run with streamable HTTP transport
mcp.run(
    transport="streamable-http",
    host=host,
    port=port,
    path=path,
)
