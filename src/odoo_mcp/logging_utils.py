"""
Shared logging utilities for the Odoo v9 MCP Server.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime


class TeeLogger:
    """Write to both stderr and a log file."""

    def __init__(self, file_path: str) -> None:
        self.terminal = sys.stderr
        # Open with restrictive permissions (0o600: owner read/write only)
        fd = os.open(file_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, mode=0o600)
        self.log = os.fdopen(fd, "a")

    def __del__(self) -> None:
        if hasattr(self, "log") and self.log:
            try:
                self.log.close()
            except Exception:
                pass

    def write(self, message: str) -> None:
        self.terminal.write(message)
        if self.log and not self.log.closed:
            self.log.write(message)
            self.log.flush()

    def flush(self) -> None:
        self.terminal.flush()
        if self.log and not self.log.closed:
            self.log.flush()

    def close(self) -> None:
        """Explicitly close the log file."""
        if self.log and not self.log.closed:
            self.log.close()


def setup_tee_logging(transport_name: str) -> str:
    """
    Set up TeeLogger for a transport runner script.

    Creates a log directory and log file, replaces sys.stderr with a TeeLogger,
    and prints a startup banner.

    Args:
        transport_name: Transport identifier for the log filename (e.g., "sse", "http")

    Returns:
        The log file path.
    """
    log_dir = "logs"
    os.makedirs(log_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = os.path.join(log_dir, f"mcp_server_{transport_name}_{timestamp}.log")

    sys.stderr = TeeLogger(log_file)  # type: ignore[assignment]

    print(
        f"[{datetime.now().isoformat()}] Starting Odoo v9 MCP Server ({transport_name.upper()} Transport)"
    )
    print(f"Logging to: {log_file}")

    return log_file
