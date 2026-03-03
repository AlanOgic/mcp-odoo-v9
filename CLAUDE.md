# CLAUDE.md

Project instructions for Claude Code when working in this repository.

## Project Overview

**Odoo v9 MCP Server** — MCP server giving AI assistants full access to Odoo v9 via JSON-RPC.

**Philosophy**: Two tools (`execute_method`, `batch_execute`) provide complete Odoo API access. No specialized tools. Add examples to COOKBOOK.md instead.

## Architecture

### Server Layer (`src/odoo_mcp/server.py` — ~1230 lines)

- FastMCP 3.x (MCP 2025-06-18 spec)
- 2 tools: `execute_method` (line 767), `batch_execute` (line 1027)
- 9 resources (deduplicated, no overlap)
- 3 prompts: search-customers, create-sales-order, odoo-exploration
- Smart limits: DEFAULT_LIMIT=100, MAX_LIMIT=1000 (line 865)

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

### Client Layer (`src/odoo_mcp/odoo_client.py` — ~775 lines)

- JSON-RPC via `/jsonrpc` endpoint, UID+password auth per request
- Singleton: `get_odoo_client()`
- Dynamic discovery:
  - `discover_model_buttons(model)` (line 289) — parses form view XML for business methods
  - `get_state_field_info(model)` (line 349) — state/stage selection values
  - `discover_workflows()` (line 394) — formal Odoo v9 workflow engine
  - `discover_state_machines()` (line 507) — models with state selection fields

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

## File Map

```
src/odoo_mcp/
  __init__.py          # Package init
  __main__.py          # CLI entry point (odoo-mcp-v9 command)
  server.py            # MCP server: tools, resources, prompts, smart limits
  odoo_client.py       # JSON-RPC client, discovery methods
run_server.py          # STDIO runner (logging to ./logs/)
run_server_sse.py      # SSE runner (port 8009)
run_server_http.py     # HTTP runner (port 8008)
pyproject.toml         # setuptools, Python 3.10+, deps: fastmcp, requests, python-dotenv
fastmcp.json           # MCP metadata
COOKBOOK.md             # 40+ usage examples (main documentation)
```

## Implementation Details

### Domain Normalization (server.py, inside execute_method)

Accepts all these formats and normalizes to Odoo-native:
- `[["field", "=", "value"]]` — native
- `{"conditions": [{...}]}` — object format
- `'[["field", "=", "value"]]'` — JSON string
- `["field", "=", "value"]` — single condition (auto-wrapped)

### Smart Limits (server.py:865-1012)

Applied to search, search_read, search_count:
1. No limit provided → apply DEFAULT_LIMIT=100
2. Limit > MAX_LIMIT → cap at 1000
3. Limit=0 or false → allow with warning
4. Result >= MAX_LIMIT → log warning

### Auth Flow

JSON-RPC authenticate → get UID → UID+password on every `execute_kw` call via `/jsonrpc`.

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

## Rules

- **Simplicity over features** — resist adding specialized tools
- **COOKBOOK.md is the main docs** — add examples there, not new tools
- Smart limits are intentionally restrictive — document pagination instead
- Odoo errors pass through directly — they're excellent and self-explanatory
- License: GPL-3.0-or-later
