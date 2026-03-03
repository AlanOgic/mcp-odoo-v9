# CLAUDE.md

Project instructions for Claude Code when working in this repository.

## Project Overview

**Odoo v9 MCP Server** — MCP server giving AI assistants full access to Odoo v9 via JSON-RPC.

**Philosophy**: Two tools (`execute_method`, `batch_execute`) provide complete Odoo API access. No specialized tools. Add examples to COOKBOOK.md instead.

## Architecture

### Server Layer (`src/odoo_mcp/server.py`)

- FastMCP 3.x (MCP 2025-06-18 spec)
- 2 tools: `execute_method`, `batch_execute`
- 9 resources (deduplicated, no overlap)
- 3 prompts: search-customers, create-sales-order, odoo-exploration
- Smart limits: DEFAULT_LIMIT=100, MAX_LIMIT=1000
- Extracted helpers: `_normalize_domain()`, `_normalize_search_args()`, `_apply_smart_limits()` — shared by both tools

**Resources:**

| Resource | Priority | Purpose |
|----------|----------|---------|
| `odoo://models` | 0.9 | List all models |
| `odoo://model/{name}/schema` | 0.9 | Fields, relationships, constraints |
| `odoo://workflows` | 0.8 | Hardcoded guides + discovered formal workflows & state machines |
| `odoo://methods/{name}` | 0.8 | ORM methods + discovered business methods & state info |
| `odoo://model/{name}` | 0.7 | Lightweight summary: name, ID, record count |
| `odoo://model/{name}/access` | 0.7 | CRUD permissions for current user |
| `odoo://record/{name}/{id}` | 0.5 | Read a single record by ID |
| `odoo://search/{name}/{domain}` | 0.5 | Search records matching a domain |
| `odoo://server/info` | 0.4 | Server version, database, installed modules |

### Client Layer (`src/odoo_mcp/odoo_client.py`)

- JSON-RPC via `/jsonrpc` endpoint, UID+password auth per request
- Singleton: `get_odoo_client()` (thread-safe, double-checked locking)
- Thread-safe request IDs: `itertools.count()`
- TTL-cached discovery (5 min): `discover_model_buttons`, `discover_workflows`, `discover_state_machines`
- XML parsing: `defusedxml.ElementTree` (XXE-safe)
- Dynamic discovery:
  - `discover_model_buttons(model)` — parses form view XML for business methods
  - `get_state_field_info(model)` — state/stage selection values
  - `discover_workflows()` — formal Odoo v9 workflow engine
  - `discover_state_machines()` — models with state selection fields

### Shared Utilities

- `src/odoo_mcp/logging_utils.py` — `TeeLogger` and `setup_tee_logging()` (used by SSE/HTTP runners)

## Quick Reference

```bash
# Dev setup
pip install -e ".[dev]"

# Run
python run_server.py         # STDIO (Claude Desktop)
python run_server_sse.py     # SSE (port 8009)
python run_server_http.py    # HTTP (port 8008)

# Code quality (run before committing)
black . && isort . && ruff check . && mypy src/

# Build
python -m build
docker build -t alanogic/mcp-odoo-v9:latest -f Dockerfile .
```

## Configuration

**Required env vars:** `ODOO_URL`, `ODOO_DB`, `ODOO_USERNAME`, `ODOO_PASSWORD`

**Optional:** `ODOO_TIMEOUT` (default 30), `ODOO_VERIFY_SSL` (default true), `HTTP_PROXY`

**Config priority:** env vars already set > `.env` file > `odoo_config.json`

**.env search order:** `$ODOO_CONFIG_DIR/.env` > `./.env` > `~/.config/odoo/.env` > `~/.env`

**JSON config validation:** Required keys (`url`, `db`, `username`, `password`) are validated on load.

## File Map

```
src/odoo_mcp/
  __init__.py          # Package init
  __main__.py          # CLI entry point (odoo-mcp-v9 command)
  server.py            # MCP server: tools, resources, prompts, smart limits
  odoo_client.py       # JSON-RPC client, discovery methods, TTL cache
  logging_utils.py     # Shared TeeLogger for transport runners
run_server.py          # STDIO runner (logging to ./logs/)
run_server_sse.py      # SSE runner (port 8009)
run_server_http.py     # HTTP runner (port 8008)
pyproject.toml         # setuptools, Python 3.10+, deps: fastmcp, requests, python-dotenv, defusedxml
fastmcp.json           # MCP metadata
COOKBOOK.md             # 40+ usage examples (main documentation)
```

## Implementation Details

### Domain Normalization (server.py, `_normalize_domain()`)

Extracted helper used by both `execute_method` and `batch_execute`.
Accepts all these formats and normalizes to Odoo-native:
- `[["field", "=", "value"]]` — native
- `{"conditions": [{...}]}` — object format
- `'[["field", "=", "value"]]'` — JSON string
- `["field", "=", "value"]` — single condition (auto-wrapped)
- `[[["field", "=", "value"]]]` — double-wrapped (auto-unwrapped)

### Smart Limits (server.py, `_apply_smart_limits()`)

Applied to search, search_read, search_count:
1. No limit provided → apply DEFAULT_LIMIT=100
2. Limit > MAX_LIMIT → cap at 1000
3. Limit=0 or false → allow with warning
4. Result >= MAX_LIMIT → log warning

### Auth Flow

JSON-RPC authenticate → get UID → UID+password on every `execute_kw` call via `/jsonrpc`.

### Discovery Cache (odoo_client.py, `_TTLCache`)

Thread-safe TTL cache (5 min default) reduces N+1 queries from discovery methods.

## Development Patterns

### Adding a Resource

```python
@mcp.resource("odoo://your-resource/{param}",
    description="...",
    annotations={"audience": ["assistant"], "priority": 0.8})
def get_your_resource(param: str) -> str:
    odoo_client = get_odoo_client()
    # ...
    return json.dumps(result, indent=2)
```

Then update README.md resource table and COOKBOOK.md if user-facing.

### Querying Best Practices

```python
# Always specify fields + filter + limit
execute_method(model="mail.message", method="search_read",
    args_json='[[["model","=","crm.lead"]]]',
    kwargs_json='{"fields": ["date","subject"], "limit": 100}')

# Paginate large datasets
execute_method(model="your.model", method="search_count", args_json='[[...]]')
execute_method(model="your.model", method="search_read",
    args_json='[[...]]',
    kwargs_json='{"limit": 100, "offset": 0}')
```

## Compatibility

Python 3.10+ | FastMCP 3.x | Odoo 9.0 (JSON-RPC) | MCP 2025-06-18

## Docker

- All Dockerfiles use Python 3.12 (configurable via `--build-arg PYTHON_VERSION=3.13`)
- Production install (`pip install .`, not editable)
- Non-root user (`appuser:appgroup`, UID 1001)
- HEALTHCHECK on all containers
- Restrictive log file permissions (0o600)

## Rules

- **Simplicity over features** — resist adding specialized tools
- **COOKBOOK.md is the main docs** — add examples there, not new tools
- Smart limits are intentionally restrictive — document pagination instead
- Odoo errors pass through directly — they're excellent and self-explanatory
- License: GPL-3.0-or-later
