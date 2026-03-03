# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2026-03-03

Specialized for Odoo v9, based on [mcp-odoo-adv](https://github.com/AlanOgic/mcp-odoo-adv) v1.0.0-beta.2.

### Changed

- **Removed JSON-2 API**: Odoo v9 uses JSON-RPC only (`/jsonrpc` endpoint)
- **Updated ir.module.module fields**: `installed_version` -> `version`, removed `application`/`license` fields
- **Updated workflows** for Odoo v9 models and methods:
  - Sales: `action_confirm` -> `action_button_confirm`, invoicing via wizard
  - Inventory: `button_validate` -> `do_transfer`, added `action_assign` step
  - CRM: `action_set_won` -> `case_mark_won` / stage write
  - HR: `hr.leave` -> `hr.holidays` (module: `hr_holidays`)
  - Accounting: `account.move` -> `account.invoice`, `action_post` -> `signal_workflow('invoice_open')`
- **Updated examples**: `customer_rank` -> `customer` (boolean field in v9)
- **Simplified client**: Removed `api_key`, `api_version` parameters, JSON-2 headers, Bearer token auth
- **Entry point**: `odoo-mcp` -> `odoo-mcp-v9`

### Kept

- 2 universal tools: `execute_method`, `batch_execute`
- 10+ MCP resources for discovery
- 3 user-facing prompts
- Smart limits system (DEFAULT_LIMIT=100, MAX_LIMIT=1000)
- 3 transports: STDIO, SSE, HTTP
- Docker support
- All documentation (adapted for v9)
