# Odoo v9 MCP Server

**Two tools. Infinite possibilities. Full Odoo v9 API access.**

An MCP (Model Context Protocol) server for **Odoo v9** ERP systems, enabling AI assistants to interact with Odoo data and functionality via JSON-RPC.

> **For Odoo 14+**, see [mcp-odoo](https://github.com/tuanle96/mcp-odoo).

---

## 30-Second Quick Start

**1. Set your credentials** (once):

```bash
mkdir -p ~/.config/odoo
cat > ~/.config/odoo/.env << 'EOF'
ODOO_URL=https://your-odoo-instance.com
ODOO_DB=your-database
ODOO_USERNAME=your-username
ODOO_PASSWORD=your-password
EOF
```

**2. Add to your AI client** and start talking to your Odoo:

<details>
<summary><b>Claude Desktop / Claude Code</b></summary>

Add to your `claude_desktop_config.json` (or `.claude.json` for Claude Code):

```json
{
  "mcpServers": {
    "odoo-v9": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/AlanOgic/mcp-odoo-v9", "odoo-mcp-v9"]
    }
  }
}
```

</details>

<details>
<summary><b>Cursor / Windsurf / any MCP client</b></summary>

Add to your MCP config (`.cursor/mcp.json`, etc.):

```json
{
  "mcpServers": {
    "odoo-v9": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/AlanOgic/mcp-odoo-v9", "odoo-mcp-v9"]
    }
  }
}
```

</details>

<details>
<summary><b>Docker</b></summary>

```bash
docker run -i --rm \
  -e ODOO_URL=https://your-instance.com \
  -e ODOO_DB=your-database \
  -e ODOO_USERNAME=your-username \
  -e ODOO_PASSWORD=your-password \
  alanogic/mcp-odoo-v9:latest
```

</details>

**3. Done.** Ask your AI: *"Show me all installed modules"* or *"Create a new customer named Acme Corp"*.

---

## What You Get

### Two Universal Tools

| Tool | What it does |
|------|-------------|
| **`execute_method`** | Call **any** Odoo method on **any** model — search, create, update, delete, confirm orders, validate invoices, anything |
| **`batch_execute`** | Run multiple operations atomically — all succeed or all rollback |

### Nine Discovery Resources

Your AI reads these automatically to understand your Odoo instance:

| Resource | What it provides |
|----------|-----------------|
| `odoo://models` | All available models |
| `odoo://model/{name}/schema` | Fields, relationships, constraints |
| `odoo://methods/{name}` | ORM + dynamically discovered business methods & state info |
| `odoo://workflows` | Workflow guides + discovered formal workflows & state machines |
| `odoo://model/{name}` | Quick summary: name, record count |
| `odoo://model/{name}/access` | Your CRUD permissions |
| `odoo://record/{name}/{id}` | Read a single record |
| `odoo://search/{name}/{domain}` | Search with domain filters |
| `odoo://server/info` | Server version, installed modules |

### Three Prompts

Ready-made templates your AI can use: **search-customers**, **create-sales-order**, **odoo-exploration**.

---

## Examples

```python
# Search customers
execute_method(
    model="res.partner",
    method="search_read",
    args_json='[[["customer", "=", true]]]',
    kwargs_json='{"fields": ["name", "email"], "limit": 20}'
)

# Create a sales order
execute_method(
    model="sale.order",
    method="create",
    args_json='[{"partner_id": 8, "order_line": [[0, 0, {"product_id": 5, "product_uom_qty": 1}]]}]'
)

# Confirm it
execute_method(
    model="sale.order",
    method="action_button_confirm",
    args_json='[[5]]'
)

# Batch: create customer + order atomically
batch_execute(
    operations=[
        {"model": "res.partner", "method": "create", "args_json": "[{\"name\": \"Acme Corp\"}]"},
        {"model": "sale.order", "method": "create", "args_json": "[{\"partner_id\": 123}]"}
    ],
    atomic=True
)
```

See **[COOKBOOK.md](COOKBOOK.md)** for 40+ more examples.

---

## Installation Options

### uvx (Recommended — zero install)

```bash
uvx --from git+https://github.com/AlanOgic/mcp-odoo-v9 odoo-mcp-v9
```

No installation, no venv, no dependencies to manage. Just run.

### pip

```bash
git clone https://github.com/AlanOgic/mcp-odoo-v9.git
cd mcp-odoo-v9
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
```

### Docker

```bash
# Build
docker build -t alanogic/mcp-odoo-v9:latest -f Dockerfile .

# Run (STDIO for Claude Desktop)
docker run -i --rm --env-file .env alanogic/mcp-odoo-v9:latest

# Run (SSE for web clients)
docker run -p 8009:8009 --env-file .env alanogic/mcp-odoo-v9:sse

# Run (HTTP for API integrations)
docker run -p 8008:8008 --env-file .env alanogic/mcp-odoo-v9:http
```

---

## Configuration

Create a `.env` file in any of these locations (checked in order):

1. `$ODOO_CONFIG_DIR/.env` — custom directory (set via env var)
2. `.env` — current working directory
3. `~/.config/odoo/.env` — user config (recommended for uvx)
4. `~/.env` — home directory

**Required variables:**

```bash
ODOO_URL=https://your-odoo-instance.com
ODOO_DB=your-database
ODOO_USERNAME=your-username
ODOO_PASSWORD=your-password
```

**Optional variables:**

```bash
ODOO_TIMEOUT=30          # Connection timeout (default: 30s)
ODOO_VERIFY_SSL=true     # SSL verification (default: true)
HTTP_PROXY=http://proxy  # HTTP proxy for Odoo connection
```

Or pass credentials directly via environment variables in your MCP client config (see Quick Start above).

---

## AI Client Setup

### Claude Desktop

Add to `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) or `%APPDATA%\Claude\claude_desktop_config.json` (Windows):

```json
{
  "mcpServers": {
    "odoo-v9": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/AlanOgic/mcp-odoo-v9", "odoo-mcp-v9"]
    }
  }
}
```

### Claude Code

Add to your project's `.mcp.json` or global `~/.claude.json`:

```json
{
  "mcpServers": {
    "odoo-v9": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/AlanOgic/mcp-odoo-v9", "odoo-mcp-v9"]
    }
  }
}
```

### With inline credentials (no .env file needed)

```json
{
  "mcpServers": {
    "odoo-v9": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/AlanOgic/mcp-odoo-v9", "odoo-mcp-v9"],
      "env": {
        "ODOO_URL": "https://your-instance.odoo.com",
        "ODOO_DB": "your-database",
        "ODOO_USERNAME": "your-username",
        "ODOO_PASSWORD": "your-password"
      }
    }
  }
}
```

### With Docker

```json
{
  "mcpServers": {
    "odoo-v9": {
      "command": "docker",
      "args": ["run", "-i", "--rm", "--env-file", "/path/to/.env", "alanogic/mcp-odoo-v9:latest"]
    }
  }
}
```

### Running the server standalone

```bash
# STDIO (default, for Claude Desktop)
python run_server.py

# SSE (port 8009, for web browsers)
python run_server_sse.py

# HTTP (port 8008, for API integrations)
python run_server_http.py
```

---

## Smart Limits

Built-in protection against accidentally returning massive datasets:

- **Default**: 100 records per query (if you don't specify a limit)
- **Maximum**: 1,000 records per query (hard cap)
- **Override**: Set `"limit"` in `kwargs_json` to your desired value
- **Unlimited**: Set `"limit": 0` (allowed with warning)

For large datasets, use pagination:

```python
# Count first
execute_method(model="res.partner", method="search_count", args_json='[[["customer","=",true]]]')

# Then paginate
execute_method(model="res.partner", method="search_read",
    args_json='[[["customer","=",true]]]',
    kwargs_json='{"fields": ["name"], "limit": 100, "offset": 0}')
```

---

## Domain Operators

Common search operators for filtering:

| Operator | Description | Example |
|----------|-------------|---------|
| `=` | Equal | `["country_id", "=", 75]` |
| `!=` | Not equal | `["active", "!=", false]` |
| `>`, `>=`, `<`, `<=` | Comparison | `["amount_total", ">=", 1000]` |
| `like`, `ilike` | Pattern match | `["name", "ilike", "acme"]` |
| `in`, `not in` | In list | `["state", "in", ["draft", "sent"]]` |

---

## Features

### AI Integration
* Two universal tools — full Odoo API access
* Dynamic discovery — business methods, workflows, and state machines introspected from the live instance
* Smart limits — automatic protection against oversized queries
* MCP 2025 compliant — latest Model Context Protocol specification

### Multiple Transports
* **STDIO** — Claude Desktop, Claude Code
* **SSE** — web browsers (port 8009)
* **HTTP** — API integrations (port 8008)
* **Docker** — pre-built containers for all transports

### Production Ready
* Odoo 9.0 via JSON-RPC
* Python 3.10 - 3.13
* Environment variables or config files
* HTTP proxy support, configurable SSL
* Enhanced logging to `./logs/`

---

## Documentation

| Doc | What's in it |
|-----|-------------|
| **[COOKBOOK.md](COOKBOOK.md)** | 40+ practical examples |
| **[USER_GUIDE.md](USER_GUIDE.md)** | Step-by-step setup guide |
| **[DOCS/TRANSPORTS.md](DOCS/TRANSPORTS.md)** | STDIO, SSE, HTTP details |
| **[DOCS/CLAUDE.md](DOCS/CLAUDE.md)** | Technical reference (850+ lines) |
| **[CHANGELOG.md](CHANGELOG.md)** | Version history |

---

## Contributing

Contributions welcome!

1. Fork the repository
2. Create feature branch (`git checkout -b feature/amazing`)
3. Commit changes
4. Push and open a Pull Request

**Philosophy:** Simplicity first. Universal tools over specialized ones. Documentation over complexity.

---

## License

GNU General Public License v3.0 or later (GPL-3.0-or-later) — See [LICENSE](LICENSE)

---

## Acknowledgments

- Original project by [Le Anh Tuan](https://github.com/tuanle96/mcp-odoo)
- Built with [FastMCP](https://github.com/jlowin/fastmcp)
- Follows [Model Context Protocol](https://modelcontextprotocol.io) specification

---

**Connect AI to Odoo v9. Two tools. Full power.**
