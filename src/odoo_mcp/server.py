"""
MCP server for Odoo v9 integration

Provides MCP tools and resources for interacting with Odoo v9 ERP systems via JSON-RPC
"""

from __future__ import annotations

import json
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from fastmcp import Context, FastMCP
from pydantic import BaseModel, Field

from .odoo_client import OdooClient, get_odoo_client


@dataclass
class AppContext:
    """Application context for the MCP server"""

    odoo: OdooClient


@asynccontextmanager
async def app_lifespan(server: FastMCP) -> AsyncIterator[AppContext]:
    """
    Application lifespan for initialization and cleanup
    """
    # Initialize Odoo client on startup
    odoo_client = get_odoo_client()

    try:
        yield AppContext(odoo=odoo_client)
    finally:
        # No cleanup needed for Odoo client
        pass


# Create MCP server
mcp = FastMCP(
    "Odoo v9 MCP Server",
    lifespan=app_lifespan,
)


# ----- Smart Limits -----
DEFAULT_LIMIT = 100  # Reasonable default to prevent huge responses
MAX_LIMIT = 1000  # Hard maximum to cap queries
SEARCH_METHODS = frozenset({"search", "search_count", "search_read"})


def _normalize_domain(domain: Any) -> list[Any]:
    """
    Normalize a search domain from various formats to Odoo-native list-of-lists.

    Accepts:
    - None → []
    - [["field", "=", "value"]] — native (passthrough)
    - {"conditions": [{...}]} — object format
    - '[[...]]' — JSON string
    - ["field", "=", "value"] — single condition (auto-wrapped)
    - [[["field", "=", "value"]]] — double-wrapped (auto-unwrapped)

    Returns:
        Normalized domain as a list of conditions.
    """
    domain_list: list[Any] = []

    # Unwrap double-wrapped domains: [[[field, op, val]]] → [[field, op, val]]
    if (
        isinstance(domain, list)
        and len(domain) == 1
        and isinstance(domain[0], list)
    ):
        domain = domain[0]

    if domain is None:
        domain_list = []
    elif isinstance(domain, dict):
        if "conditions" in domain:
            conditions = domain.get("conditions", [])
            for cond in conditions:
                if isinstance(cond, dict) and all(
                    k in cond for k in ["field", "operator", "value"]
                ):
                    domain_list.append(
                        [cond["field"], cond["operator"], cond["value"]]
                    )
    elif isinstance(domain, list):
        if not domain:
            domain_list = []
        elif all(isinstance(item, list) for item in domain) or any(
            item in ["&", "|", "!"] for item in domain
        ):
            domain_list = domain
        elif len(domain) >= 3 and isinstance(domain[0], str):
            domain_list = [domain]
    elif isinstance(domain, str):
        try:
            parsed_domain = json.loads(domain)
            if isinstance(parsed_domain, dict) and "conditions" in parsed_domain:
                conditions = parsed_domain.get("conditions", [])
                for cond in conditions:
                    if isinstance(cond, dict) and all(
                        k in cond for k in ["field", "operator", "value"]
                    ):
                        domain_list.append(
                            [cond["field"], cond["operator"], cond["value"]]
                        )
            elif isinstance(parsed_domain, list):
                domain_list = parsed_domain
        except json.JSONDecodeError:
            print(
                f"⚠️ Domain string is not valid JSON, using empty domain: {domain[:200]}",
                file=sys.stderr,
            )
            domain_list = []

    # Validate conditions
    if domain_list:
        valid_conditions: list[Any] = []
        for cond in domain_list:
            if isinstance(cond, str) and cond in ["&", "|", "!"]:
                valid_conditions.append(cond)
                continue
            if (
                isinstance(cond, list)
                and len(cond) == 3
                and isinstance(cond[0], str)
                and isinstance(cond[1], str)
            ):
                valid_conditions.append(cond)
        domain_list = valid_conditions

    return domain_list


def _normalize_search_args(method: str, args: list[Any]) -> list[Any]:
    """
    Normalize domain in args[0] for search methods and return updated args.
    """
    if method not in SEARCH_METHODS or not args:
        return args

    normalized_args = list(args)
    if len(normalized_args) > 0:
        domain_list = _normalize_domain(normalized_args[0])
        normalized_args[0] = domain_list
        print(
            f"Executing {method} with normalized domain: {domain_list}",
            file=sys.stderr,
        )

    return normalized_args


def _apply_smart_limits(method: str, kwargs: dict[str, Any]) -> dict[str, Any]:
    """
    Apply smart limits for search methods. Returns updated kwargs.
    """
    if method not in SEARCH_METHODS or method == "search_count":
        return kwargs

    if "limit" not in kwargs:
        kwargs["limit"] = DEFAULT_LIMIT
        print(
            f"⚠️  No limit specified for {method}, applying default limit={DEFAULT_LIMIT}",
            file=sys.stderr,
        )
    elif kwargs.get("limit", 0) > MAX_LIMIT:
        original_limit = kwargs["limit"]
        kwargs["limit"] = MAX_LIMIT
        print(
            f"⚠️  Requested limit={original_limit} exceeds maximum, capping to limit={MAX_LIMIT}",
            file=sys.stderr,
        )
    elif kwargs.get("limit", 0) == 0 or kwargs.get("limit") is False:
        print(
            "⚠️  WARNING: Unlimited query requested! This may return massive datasets.",
            file=sys.stderr,
        )

    return kwargs


# ----- MCP Resources -----
# Note: Resources use get_odoo_client() (thread-safe singleton) because FastMCP
# resources don't receive a Context object. Tools use the lifespan context.
# Both paths return the same singleton instance.


@mcp.resource(
    "odoo://models",
    description="List all available models in the Odoo system",
    annotations={
        "audience": ["assistant"],
        "priority": 0.9,
    },
)
def get_models() -> str:
    """Lists all available models in the Odoo system"""
    odoo_client = get_odoo_client()
    models = odoo_client.get_models()
    return json.dumps(models, indent=2)


@mcp.resource(
    "odoo://model/{model_name}",
    description="Lightweight model summary: name, ID, record count. Use odoo://model/{model_name}/schema for field definitions.",
    annotations={
        "audience": ["assistant"],
        "priority": 0.7,
    },
)
def get_model_info(model_name: str) -> str:
    """
    Get a lightweight summary of a specific model (no field definitions).

    Returns model name, display name, model ID, and total record count.
    For field definitions, use odoo://model/{model_name}/schema instead.

    Parameters:
        model_name: Name of the Odoo model (e.g., 'res.partner')
    """
    odoo_client = get_odoo_client()
    try:
        # Get basic model metadata from ir.model
        model_info = odoo_client.get_model_info(model_name)
        if "error" in model_info:
            return json.dumps(model_info, indent=2)

        # Get record count
        record_count = odoo_client.execute_method(model_name, "search_count", [])

        summary = {
            "model": model_name,
            "display_name": model_info.get("name", ""),
            "model_id": model_info.get("id"),
            "record_count": record_count,
            "schema_resource": f"odoo://model/{model_name}/schema",
            "note": "Use the schema resource for field definitions, relationships, and constraints.",
        }

        return json.dumps(summary, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)}, indent=2)


@mcp.resource(
    "odoo://record/{model_name}/{record_id}",
    description="Get detailed information of a specific record by ID",
    annotations={
        "audience": ["user", "assistant"],
        "priority": 0.5,
    },
)
def get_record(model_name: str, record_id: str) -> str:
    """
    Get a specific record by ID

    Parameters:
        model_name: Name of the Odoo model (e.g., 'res.partner')
        record_id: ID of the record
    """
    odoo_client = get_odoo_client()
    try:
        record_id_int = int(record_id)
        record = odoo_client.read_records(model_name, [record_id_int])
        if not record:
            return json.dumps(
                {"error": f"Record not found: {model_name} ID {record_id}"}, indent=2
            )
        return json.dumps(record[0], indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)}, indent=2)


@mcp.resource(
    "odoo://search/{model_name}/{domain}",
    description="Search for records matching the domain",
    annotations={
        "audience": ["user", "assistant"],
        "priority": 0.5,
    },
)
def search_records_resource(model_name: str, domain: str) -> str:
    """
    Search for records that match a domain

    Parameters:
        model_name: Name of the Odoo model (e.g., 'res.partner')
        domain: Search domain in JSON format (e.g., '[["name", "ilike", "test"]]')
    """
    odoo_client = get_odoo_client()
    try:
        # Parse domain from JSON string
        domain_list = json.loads(domain)

        # Perform search_read for efficiency
        results = odoo_client.search_read(model_name, domain_list, limit=DEFAULT_LIMIT)

        return json.dumps(results, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)}, indent=2)


@mcp.resource(
    "odoo://model/{model_name}/schema",
    description="Complete schema for a model including fields, relationships, and constraints",
    annotations={
        "audience": ["assistant"],
        "priority": 0.9,
    },
)
def get_model_schema(model_name: str) -> str:
    """
    Get comprehensive schema information for a model

    Includes:
    - Field definitions with types, constraints, help text
    - Relationships (many2one, one2many, many2many)
    - Required fields
    - Computed fields
    - Default values

    Parameters:
        model_name: Name of the Odoo model (e.g., 'res.partner')
    """
    odoo_client = get_odoo_client()
    try:
        # Get field definitions
        fields = odoo_client.get_model_fields(model_name)

        # Organize fields by category
        schema = {
            "model": model_name,
            "fields": fields,
            "relationships": {},
            "required_fields": [],
            "readonly_fields": [],
            "computed_fields": [],
        }

        # Categorize fields
        for field_name, field_def in fields.items():
            field_type = field_def.get("type", "")

            # Track relationships
            if field_type in ["many2one", "one2many", "many2many"]:
                schema["relationships"][field_name] = {
                    "type": field_type,
                    "relation": field_def.get("relation", ""),
                    "string": field_def.get("string", ""),
                }

            # Track required fields
            if field_def.get("required"):
                schema["required_fields"].append(field_name)

            # Track readonly fields
            if field_def.get("readonly"):
                schema["readonly_fields"].append(field_name)

            # Track computed fields
            if field_def.get("store") is False or field_def.get("compute"):
                schema["computed_fields"].append(field_name)

        return json.dumps(schema, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)}, indent=2)


@mcp.resource(
    "odoo://model/{model_name}/access",
    description="Access rights for the current user on this model",
    annotations={
        "audience": ["assistant"],
        "priority": 0.7,
    },
)
def get_model_access(model_name: str) -> str:
    """
    Check what operations the current user can perform on a model

    Returns permissions for: read, write, create, unlink (delete)

    Parameters:
        model_name: Name of the Odoo model (e.g., 'res.partner')
    """
    odoo_client = get_odoo_client()
    try:
        # Check access rights for all CRUD operations
        access_rights = {}
        operations = ["read", "write", "create", "unlink"]

        for operation in operations:
            try:
                # Use check_access_rights method
                has_access = odoo_client.execute_method(
                    model_name,
                    "check_access_rights",
                    operation,
                    False,  # raise_exception=False
                )
                access_rights[operation] = has_access
            except Exception as e:
                print(
                    f"Access check for {model_name}.{operation} failed: {e}",
                    file=sys.stderr,
                )
                access_rights[operation] = False

        return json.dumps(
            {
                "model": model_name,
                "access_rights": access_rights,
                "note": "These are model-level permissions. Record-level rules may further restrict access.",
            },
            indent=2,
        )
    except Exception as e:
        return json.dumps({"error": str(e)}, indent=2)


@mcp.resource(
    "odoo://workflows",
    description="Business workflows: hardcoded guides for common modules + dynamically discovered formal workflows and state machines",
    annotations={
        "audience": ["assistant"],
        "priority": 0.8,
    },
)
def get_workflows() -> str:
    """
    Discover available business workflows based on installed Odoo modules.

    Returns:
    - Hardcoded workflow guides for common modules (Sales, Inventory, CRM, etc.)
    - Dynamically discovered formal Odoo v9 workflows (workflow engine)
    - Dynamically discovered state machines (models with state selection fields)
    """
    odoo_client = get_odoo_client()
    try:
        # Get installed modules (v9 does not have 'application' field)
        modules = odoo_client.search_read(
            "ir.module.module",
            [("state", "=", "installed")],
            fields=["name", "shortdesc"],
            limit=None,
        )

        module_names = {m["name"]: m.get("shortdesc", "") for m in modules}

        # Define known workflows for common modules (Odoo v9 methods)
        workflows = {}

        if "sale" in module_names:
            workflows["sales"] = {
                "module": "sale",
                "title": "Sales Management",
                "workflows": [
                    {
                        "name": "quotation_to_order",
                        "steps": [
                            "Create quotation (sale.order with state='draft')",
                            "Send quotation to customer (method: action_quotation_send)",
                            "Confirm order (method: action_button_confirm)",
                            "Create invoice via wizard (sale.advance.payment.inv)",
                        ],
                        "model": "sale.order",
                    },
                    {
                        "name": "create_customer_order",
                        "steps": [
                            "Create/find customer (res.partner with customer=True)",
                            "Create sale.order with partner_id",
                            "Add order lines (sale.order.line)",
                            "Confirm order (method: action_button_confirm)",
                        ],
                        "models": ["res.partner", "sale.order", "sale.order.line"],
                    },
                ],
            }

        if "stock" in module_names:
            workflows["inventory"] = {
                "module": "stock",
                "title": "Inventory Management",
                "workflows": [
                    {
                        "name": "product_transfer",
                        "steps": [
                            "Create picking (stock.picking)",
                            "Add move lines (stock.move)",
                            "Check availability (method: action_assign)",
                            "Validate transfer (method: do_transfer)",
                        ],
                        "model": "stock.picking",
                    },
                    {
                        "name": "inventory_adjustment",
                        "steps": [
                            "Create inventory adjustment (stock.inventory)",
                            "Set product quantities",
                            "Validate adjustment",
                        ],
                        "model": "stock.inventory",
                    },
                ],
            }

        if "crm" in module_names:
            workflows["crm"] = {
                "module": "crm",
                "title": "CRM / Leads",
                "workflows": [
                    {
                        "name": "lead_to_opportunity",
                        "steps": [
                            "Create lead (crm.lead)",
                            "Convert to opportunity (method: convert_opportunity)",
                            "Move through stages (write stage_id)",
                            "Mark as won (method: case_mark_won or write stage_id to won stage)",
                        ],
                        "model": "crm.lead",
                    }
                ],
            }

        if "hr_holidays" in module_names:
            workflows["hr"] = {
                "module": "hr_holidays",
                "title": "Human Resources - Leave Management",
                "workflows": [
                    {
                        "name": "leave_request",
                        "steps": [
                            "Create leave request (hr.holidays with type='remove')",
                            "Submit for approval (method: holidays_validate)",
                            "Manager validates or refuses (method: holidays_refuse)",
                        ],
                        "model": "hr.holidays",
                    }
                ],
            }

        if "account" in module_names:
            workflows["accounting"] = {
                "module": "account",
                "title": "Accounting",
                "workflows": [
                    {
                        "name": "create_invoice",
                        "steps": [
                            "Create invoice (account.invoice with type='out_invoice')",
                            "Add invoice lines (account.invoice.line)",
                            "Validate invoice (method: signal_workflow with signal='invoice_open')",
                            "Register payment",
                        ],
                        "model": "account.invoice",
                    }
                ],
            }

        if "project" in module_names:
            workflows["projects"] = {
                "module": "project",
                "title": "Project Management",
                "workflows": [
                    {
                        "name": "task_lifecycle",
                        "steps": [
                            "Create project (project.project)",
                            "Create tasks (project.task)",
                            "Assign to users",
                            "Track progress through stages",
                        ],
                        "models": ["project.project", "project.task"],
                    }
                ],
            }

        # Dynamic discovery: formal Odoo v9 workflows
        discovered_workflows = odoo_client.discover_workflows()

        # Dynamic discovery: state machines (models with state selection fields)
        # Exclude models already covered by hardcoded workflows above
        hardcoded_models = set()
        for wf_group in workflows.values():
            for wf in wf_group.get("workflows", []):
                if "model" in wf:
                    hardcoded_models.add(wf["model"])
                for m in wf.get("models", []):
                    hardcoded_models.add(m)

        discovered_state_machines = odoo_client.discover_state_machines()
        # Filter out models already covered by hardcoded workflows
        discovered_state_machines = [
            sm
            for sm in discovered_state_machines
            if sm["model"] not in hardcoded_models
        ]

        result = {
            "installed_modules": list(module_names.keys()),
            "available_workflows": workflows,
            "note": "Use execute_method tool to call the methods mentioned in workflow steps",
        }

        if discovered_workflows:
            result["discovered_workflows"] = discovered_workflows

        if discovered_state_machines:
            result["discovered_state_machines"] = discovered_state_machines

        return json.dumps(result, indent=2)

    except Exception as e:
        return json.dumps({"error": str(e)}, indent=2)


@mcp.resource(
    "odoo://methods/{model_name}",
    description="""Available methods for a model (ORM + dynamically discovered business methods).

    ⚡ IMPORTANT: If a specialized tool doesn't exist, use the execute_method tool!
    The execute_method tool can call ANY of these methods.

    Includes:
    - Standard ORM methods (search, create, write, etc.)
    - Business methods discovered from form view buttons (e.g., action_confirm)
    - State/stage field info for workflow transitions

    Example: execute_method(model='res.partner', method='search_read',
                           args_json='[[...domain...]]', kwargs_json='{...}')
    """,
    annotations={
        "audience": ["assistant"],
        "priority": 0.8,
    },
)
def get_methods(model_name: str) -> str:
    """
    Get available methods for a model, including dynamically discovered business methods.

    Returns:
    - Standard ORM methods (read, write, create, etc.)
    - Business methods found in form view buttons (action_confirm, etc.)
    - State/stage field info for understanding workflow transitions

    Parameters:
        model_name: Name of the Odoo model (e.g., 'res.partner')
    """
    odoo_client = get_odoo_client()
    try:
        # Static ORM methods (always available)
        common_methods = {
            "read_methods": [
                {
                    "name": "search",
                    "description": "Search for record IDs matching domain",
                    "params": ["domain", "offset", "limit", "order", "count"],
                },
                {
                    "name": "search_read",
                    "description": "Search and read records in one call",
                    "params": ["domain", "fields", "offset", "limit", "order"],
                },
                {
                    "name": "read",
                    "description": "Read specific fields from records",
                    "params": ["ids", "fields"],
                },
                {
                    "name": "search_count",
                    "description": "Count records matching domain",
                    "params": ["domain"],
                },
                {
                    "name": "name_search",
                    "description": "Search records by name",
                    "params": ["name", "args", "operator", "limit"],
                },
                {
                    "name": "name_get",
                    "description": "Get display names for records",
                    "params": ["ids"],
                },
                {
                    "name": "fields_get",
                    "description": "Get field definitions",
                    "params": ["allfields", "attributes"],
                },
            ],
            "write_methods": [
                {
                    "name": "create",
                    "description": "Create new record(s)",
                    "params": ["vals"],
                },
                {
                    "name": "write",
                    "description": "Update existing record(s)",
                    "params": ["ids", "vals"],
                },
                {
                    "name": "unlink",
                    "description": "Delete record(s)",
                    "params": ["ids"],
                },
            ],
            "note": f"Use execute_method tool to call these methods on {model_name}",
            "example": {
                "tool": "execute_method",
                "model": model_name,
                "method": "search_read",
                "args": [[["name", "ilike", "example"]]],
                "kwargs": {"fields": ["id", "name"], "limit": 10},
            },
        }

        # Dynamic discovery: business methods from form view buttons
        orm_method_names = {
            m["name"]
            for group in ["read_methods", "write_methods"]
            for m in common_methods[group]
        }
        buttons = odoo_client.discover_model_buttons(model_name)
        if buttons:
            # Filter out methods already listed in ORM methods
            business_methods = [b for b in buttons if b["name"] not in orm_method_names]
            if business_methods:
                common_methods["business_methods"] = business_methods

        # Dynamic discovery: state/stage field info
        state_info = odoo_client.get_state_field_info(model_name)
        if state_info:
            common_methods["state_management"] = state_info

        return json.dumps(common_methods, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)}, indent=2)


@mcp.resource(
    "odoo://server/info",
    description="Get Odoo server information including version and installed modules",
    annotations={
        "audience": ["user", "assistant"],
        "priority": 0.4,
    },
)
def get_server_info() -> str:
    """
    Get Odoo server metadata

    Returns server version, database name, and list of installed modules
    """
    odoo_client = get_odoo_client()
    try:
        # Get server version info - search for base module
        base_ids = odoo_client._execute(
            "ir.module.module",
            "search",
            [["state", "=", "installed"], ["name", "=", "base"]],
        )
        # Read version field (v9 uses 'version' not 'installed_version')
        version_info = (
            odoo_client._execute("ir.module.module", "read", base_ids[:1], ["version"])
            if base_ids
            else []
        )

        # Get all installed modules
        module_ids = odoo_client._execute(
            "ir.module.module", "search", [["state", "=", "installed"]]
        )

        # Read all installed modules with v9-compatible fields
        installed_modules = (
            odoo_client._execute(
                "ir.module.module",
                "read",
                module_ids,
                ["name", "shortdesc", "author", "version", "state", "category_id"],
            )
            if module_ids
            else []
        )

        # Get database name from config
        db_name = odoo_client.db if hasattr(odoo_client, "db") else "unknown"

        server_info = {
            "database": db_name,
            "odoo_version": (
                version_info[0].get("version", "unknown") if version_info else "unknown"
            ),
            "installed_modules_count": len(module_ids) if module_ids else 0,
            "installed_modules": [
                {
                    "name": mod.get("name"),
                    "title": mod.get("shortdesc"),
                    "version": mod.get("version"),
                    "author": mod.get("author", "Unknown"),
                    "state": mod.get("state", "unknown"),
                    "category": (
                        mod.get("category_id", [False, ""])[1]
                        if isinstance(mod.get("category_id"), (list, tuple))
                        else ""
                    ),
                }
                for mod in installed_modules
            ],
        }

        return json.dumps(server_info, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)}, indent=2)


# ----- Pydantic models for type safety -----


class ExecuteMethodResponse(BaseModel):
    """Response model for the execute_method tool."""

    success: bool = Field(
        description="Indicates if the method execution was successful"
    )
    result: Any | None = Field(
        default=None, description="Result of the method execution"
    )
    error: str | None = Field(default=None, description="Error message, if any")


class BatchExecuteResponse(BaseModel):
    """Response model for batch_execute tool"""

    success: bool = Field(description="Whether all operations succeeded")
    results: list[dict[str, Any]] = Field(description="Results for each operation")
    total_operations: int = Field(description="Total number of operations attempted")
    successful_operations: int = Field(description="Number of successful operations")
    failed_operations: int = Field(description="Number of failed operations")
    error: str | None = Field(
        default=None, description="Overall error message if batch failed"
    )


# ----- MCP Tools -----


@mcp.tool(
    description="""⚡ UNIVERSAL TOOL - Execute ANY Odoo method on ANY model

    This is THE CORE tool. Full Odoo API access. No limitations.
    Can call ANY of the hundreds of Odoo methods across all models.

    Common use cases:
    - Creating records: method='create'
    - Searching: method='search_read'
    - Reading records: method='read'
    - Updating: method='write'
    - Deleting: method='unlink'
    - Custom methods: method='action_button_confirm', 'signal_workflow', etc.

    🛡️ SMART LIMITS (to prevent massive data returns):
    - Default limit: 100 records (if not specified)
    - Maximum limit: 1000 records (hard cap)
    - Override: Set "limit" in kwargs_json to your desired value
    - Unlimited: Set "limit": 0 or "limit": false (will warn)

    Before using, check:
    - odoo://model/{model}/schema for field definitions
    - odoo://methods/{model} for available methods

    Odoo provides excellent error messages for validation - no pre-check needed!
    """,
    output_schema=ExecuteMethodResponse.model_json_schema(),
)
def execute_method(
    ctx: Context,
    model: str,
    method: str,
    args_json: str | None = None,
    kwargs_json: str | None = None,
) -> dict[str, Any]:
    """
    Execute ANY method on an Odoo model - UNIVERSAL FALLBACK TOOL

    ⚡ This tool can call ANY Odoo method that doesn't have a specialized tool.
    It's your escape hatch for the full power of Odoo's API.

    Parameters:
        model: The model name (e.g., 'res.partner', 'sale.order', 'crm.lead')
        method: Method name to execute (e.g., 'create', 'search_read', 'write', 'action_button_confirm')
        args_json: JSON string for positional arguments (e.g., '[[["name", "=", "Test"]]]')
        kwargs_json: JSON string for keyword arguments (e.g., '{"fields": ["name", "email"], "limit": 10}')

    Common Examples (Odoo v9):

        Create a customer:
            model='res.partner'
            method='create'
            args_json='[{"name": "Acme Corp", "email": "info@acme.com", "customer": true}]'

        Search partners:
            model='res.partner'
            method='search_read'
            args_json='[[["name", "ilike", "Acme"]]]'
            kwargs_json='{"fields": ["name", "email"], "limit": 5}'

        Update records:
            model='res.partner'
            method='write'
            args_json='[[1, 2, 3], {"phone": "+1234567890"}]'

        Delete records:
            model='res.partner'
            method='unlink'
            args_json='[[1, 2, 3]]'

        Get field definitions:
            model='crm.lead'
            method='fields_get'

        Call custom/business methods (v9):
            model='sale.order'
            method='action_button_confirm'
            args_json='[[5]]'  # Order ID 5

    Returns:
        Dictionary containing:
        - success: Boolean indicating success
        - result: Result of the method (if success)
        - error: Error message (if failure)

    Pro Tips:
    - Check odoo://model/{model}/schema for required fields
    - Check odoo://methods/{model} for available methods
    - For workflows, see odoo://workflows for step-by-step guides
    """
    odoo = ctx.request_context.lifespan_context.odoo
    try:
        # Parse JSON strings to actual Python objects
        args = []
        kwargs = {}

        if args_json:
            try:
                args = json.loads(args_json)
                if not isinstance(args, list):
                    return {
                        "success": False,
                        "error": f"args_json must be a JSON array, got: {type(args).__name__}",
                    }
            except json.JSONDecodeError as e:
                return {
                    "success": False,
                    "error": f"Invalid JSON in args_json: {str(e)}",
                }

        if kwargs_json:
            try:
                kwargs = json.loads(kwargs_json)
                if not isinstance(kwargs, dict):
                    return {
                        "success": False,
                        "error": f"kwargs_json must be a JSON object, got: {type(kwargs).__name__}",
                    }
            except json.JSONDecodeError as e:
                return {
                    "success": False,
                    "error": f"Invalid JSON in kwargs_json: {str(e)}",
                }

        # Normalize domain and apply smart limits
        args = _normalize_search_args(method, args)
        kwargs = _apply_smart_limits(method, kwargs)

        # Apply limits for read method too
        if method == "read" and args:
            # read(ids, fields) - check if ids list is huge
            if isinstance(args[0], list) and len(args[0]) > MAX_LIMIT:
                print(
                    f"⚠️  WARNING: Reading {len(args[0])} records at once! Consider batching.",
                    file=sys.stderr,
                )

        result = odoo.execute_method(model, method, *args, **kwargs)

        # Warn if result is very large
        if isinstance(result, list) and len(result) >= MAX_LIMIT:
            print(
                f"⚠️  Large result set returned: {len(result)} records. Consider adding filters.",
                file=sys.stderr,
            )

        return {"success": True, "result": result}
    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool(
    description="Execute multiple Odoo operations in a batch - Sequential execution with fail-fast support",
    output_schema=BatchExecuteResponse.model_json_schema(),
)
def batch_execute(
    ctx: Context, operations: list[dict[str, Any]], atomic: bool = True
) -> BatchExecuteResponse:
    """
    Execute multiple operations sequentially in one call

    IMPORTANT: Operations are NOT truly atomic. Each operation executes in its own
    JSON-RPC call with its own database transaction. Previously successful operations
    CANNOT be rolled back if a later operation fails.

    When atomic=True (default): stops executing on first failure (fail-fast).
    When atomic=False: continues executing remaining operations after a failure.

    Parameters:
        operations: List of operations, each with:
                   - model: str (required)
                   - method: str (required)
                   - args: list (optional, direct format) OR args_json: str (JSON string format)
                   - kwargs: dict (optional, direct format) OR kwargs_json: str (JSON string format)
        atomic: If True, stop on first failure (default). Previously committed operations are NOT rolled back.

    Examples:
        # Create customer then order sequentially
        batch_execute(operations=[
            {
                "model": "res.partner",
                "method": "create",
                "args_json": '[{"name": "Acme Corp", "customer": true}]'
            },
            {
                "model": "sale.order",
                "method": "create",
                "args_json": '[{"partner_id": 123, "order_line": [...]}]'
            }
        ], atomic=True)

    Returns:
        BatchExecuteResponse with results for each operation
    """
    odoo = ctx.request_context.lifespan_context.odoo
    results = []
    successful = 0
    failed = 0

    try:
        for idx, op in enumerate(operations):
            try:
                model = op.get("model")
                method = op.get("method")
                args_json = op.get("args_json")
                kwargs_json = op.get("kwargs_json")
                args_direct = op.get("args")
                kwargs_direct = op.get("kwargs")

                if not model or not method:
                    raise ValueError(
                        f"Operation {idx}: 'model' and 'method' are required"
                    )

                # Parse arguments - support both JSON strings and direct objects
                if args_json:
                    args = (
                        json.loads(args_json)
                        if isinstance(args_json, str)
                        else args_json
                    )
                elif args_direct is not None:
                    args = args_direct
                else:
                    args = []

                if kwargs_json:
                    kwargs = (
                        json.loads(kwargs_json)
                        if isinstance(kwargs_json, str)
                        else kwargs_json
                    )
                elif kwargs_direct is not None:
                    kwargs = kwargs_direct
                else:
                    kwargs = {}

                # Normalize domain and apply smart limits (parity with execute_method)
                if isinstance(args, list):
                    args = _normalize_search_args(method, args)
                if isinstance(kwargs, dict):
                    kwargs = _apply_smart_limits(method, kwargs)

                # Execute the operation
                result = odoo.execute_method(model, method, *args, **kwargs)

                results.append(
                    {"operation_index": idx, "success": True, "result": result}
                )
                successful += 1

            except Exception as e:
                results.append(
                    {"operation_index": idx, "success": False, "error": str(e)}
                )
                failed += 1

                # If atomic, fail fast
                if atomic:
                    return BatchExecuteResponse(
                        success=False,
                        results=results,
                        total_operations=len(operations),
                        successful_operations=successful,
                        failed_operations=failed,
                        error=f"Batch stopped at operation {idx}: {str(e)} (fail-fast mode — {successful} prior operation(s) were already committed and cannot be rolled back)",
                    )

        return BatchExecuteResponse(
            success=(failed == 0),
            results=results,
            total_operations=len(operations),
            successful_operations=successful,
            failed_operations=failed,
            error=None if failed == 0 else f"{failed} operations failed",
        )

    except Exception as e:
        return BatchExecuteResponse(
            success=False,
            results=results,
            total_operations=len(operations),
            successful_operations=successful,
            failed_operations=failed,
            error=f"Batch execution failed: {str(e)}",
        )


# ----- MCP Prompts -----


@mcp.prompt(name="search-customers")
def search_customers_prompt(city: str = "", country: str = "") -> list[dict[str, str]]:
    """Search for customers with optional location filters"""
    filter_desc = []
    if city:
        filter_desc.append(f"in {city}")
    if country:
        filter_desc.append(f"from {country}")

    location_filter = " ".join(filter_desc) if filter_desc else "with any location"

    return [
        {
            "role": "user",
            "content": f"""Find customers {location_filter}.

Use execute_method with:
- model='res.partner'
- method='search_read'
- domain: [["customer", "=", true]]
- Add location filters if needed

Example:
execute_method(
    model='res.partner',
    method='search_read',
    args_json='[[["customer", "=", true]]]',
    kwargs_json='{{"fields": ["name", "email", "phone", "city", "country_id"], "limit": 20}}'
)

Check odoo://model/res.partner/schema for all available fields.
""",
        }
    ]


@mcp.prompt(name="create-sales-order")
def create_sales_order_prompt(customer_id: int = 0) -> list[dict[str, str]]:
    """Create a sales order in Odoo"""
    return [
        {
            "role": "user",
            "content": f"""Create a new sales order{' for customer ID ' + str(customer_id) if customer_id > 0 else ''}.

Use execute_method to create:
1. Find customer (if not provided): model='res.partner', method='search_read', domain=[["customer","=",true]]
2. Create order: model='sale.order', method='create'
3. Optionally confirm: model='sale.order', method='action_button_confirm'

Check schemas:
- odoo://model/sale.order/schema for required fields
- odoo://model/sale.order.line/schema for order lines

See odoo://workflows for complete sales workflow.
""",
        }
    ]


@mcp.prompt(name="odoo-exploration")
def odoo_exploration_prompt() -> list[dict[str, str]]:
    """Discover capabilities of this Odoo instance"""
    return [
        {
            "role": "user",
            "content": """Explore this Odoo instance systematically:

1. **Server Info**: Read odoo://server/info
2. **Workflows**: Read odoo://workflows
3. **Key Models**: Check odoo://models
4. **Permissions**: Check odoo://model/{model}/access for key models

Provide summary of:
- Odoo version and installed apps
- Available workflows
- My permissions
- 3-5 suggested tasks
""",
        }
    ]
