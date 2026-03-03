"""
Odoo v9 JSON-RPC client for MCP server integration
"""

from __future__ import annotations

import itertools
import json
import os
import re
import sys
import threading
import time
import urllib.parse
from typing import Any

import defusedxml.ElementTree as ET
import requests
from dotenv import load_dotenv


# ----- TTL Cache -----

_DISCOVERY_CACHE_TTL = 300  # 5 minutes


class _TTLCache:
    """Simple thread-safe TTL cache for discovery results."""

    def __init__(self, ttl: float = _DISCOVERY_CACHE_TTL) -> None:
        self._ttl = ttl
        self._store: dict[str, tuple[float, Any]] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> Any | None:
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            ts, value = entry
            if time.monotonic() - ts > self._ttl:
                del self._store[key]
                return None
            return value

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            self._store[key] = (time.monotonic(), value)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()


class OdooClient:
    """Client for interacting with Odoo v9 via JSON-RPC"""

    def __init__(
        self,
        url: str,
        db: str,
        username: str,
        password: str,
        timeout: int = 30,
        verify_ssl: bool = True,
    ) -> None:
        """
        Initialize the Odoo v9 client with connection parameters

        Args:
            url: Odoo server URL (with or without protocol)
            db: Database name
            username: Login username
            password: Login password
            timeout: Connection timeout in seconds
            verify_ssl: Whether to verify SSL certificates
        """
        # Ensure URL has a protocol — default to HTTPS for security
        if not re.match(r"^https?://", url):
            url = f"https://{url}"
            print(
                f"No URL scheme provided, defaulting to HTTPS: {url}",
                file=sys.stderr,
            )

        # Remove trailing slash from URL if present
        url = url.rstrip("/")

        self.url = url
        self.db = db
        self.username = username
        self.password = password
        self.uid = None

        if not password:
            raise ValueError("password is required for JSON-RPC API")

        # Set timeout and SSL verification
        self.timeout = timeout
        self.verify_ssl = verify_ssl

        # Setup session
        self.session = requests.Session()
        self.session.verify = verify_ssl

        # HTTP/HTTPS proxy support
        http_proxy = os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy")
        https_proxy = (
            os.environ.get("HTTPS_PROXY")
            or os.environ.get("https_proxy")
            or http_proxy
        )
        if http_proxy or https_proxy:
            self.session.proxies = {}
            if http_proxy:
                self.session.proxies["http"] = http_proxy
            if https_proxy:
                self.session.proxies["https"] = https_proxy

        # Parse hostname for logging
        parsed_url = urllib.parse.urlparse(self.url)
        self.hostname = parsed_url.netloc

        # JSON-RPC endpoint
        self.jsonrpc_url = f"{self.url}/jsonrpc"

        # Thread-safe request ID counter
        self._request_id_counter = itertools.count(1)

        # TTL cache for discovery results
        self._cache = _TTLCache()

        # Connect and authenticate
        self._connect()

    def _jsonrpc_call(self, service: str, method: str, *args: Any) -> Any:
        """
        Make a JSON-RPC 1.x call to Odoo

        Args:
            service: Service name ('common' or 'object')
            method: Method name to call
            *args: Arguments to pass to the method

        Returns:
            Result of the method call
        """
        request_id = next(self._request_id_counter)

        payload = {
            "jsonrpc": "1.0",
            "method": "call",
            "params": {"service": service, "method": method, "args": list(args)},
            "id": request_id,
        }

        try:
            response = self.session.post(
                self.jsonrpc_url,
                json=payload,
                timeout=self.timeout,
                headers={"Content-Type": "application/json"},
            )
            response.raise_for_status()

            result = response.json()

            if "error" in result:
                error_data = result["error"]
                error_msg = error_data.get("data", {}).get("message", str(error_data))
                raise ValueError(f"Odoo error: {error_msg}")

            return result.get("result")

        except requests.exceptions.Timeout as e:
            raise TimeoutError(f"Request timeout after {self.timeout}s: {str(e)}")
        except requests.exceptions.ConnectionError as e:
            raise ConnectionError(f"Failed to connect to Odoo server: {str(e)}")
        except requests.exceptions.RequestException as e:
            raise ValueError(f"Request failed: {str(e)}")

    def _connect(self) -> None:
        """Initialize the JSON-RPC connection and authenticate"""
        print(f"Connecting to Odoo v9 at: {self.url}", file=sys.stderr)
        print(f"  Hostname: {self.hostname}", file=sys.stderr)
        print(
            f"  Timeout: {self.timeout}s, Verify SSL: {self.verify_ssl}",
            file=sys.stderr,
        )
        print(f"  JSON-RPC endpoint: {self.jsonrpc_url}", file=sys.stderr)

        # Authenticate and get user ID
        print(
            f"Authenticating with database: {self.db}, username: {self.username}",
            file=sys.stderr,
        )
        try:
            self.uid = self._jsonrpc_call(
                "common", "authenticate", self.db, self.username, self.password, {}
            )
            if not self.uid:
                raise ValueError("Authentication failed: Invalid username or password")

            print(f"  Authenticated successfully with UID: {self.uid}", file=sys.stderr)

        except (TimeoutError, ConnectionError) as e:
            print(f"Connection error: {str(e)}", file=sys.stderr)
            raise
        except Exception as e:
            print(f"Authentication error: {str(e)}", file=sys.stderr)
            raise ValueError(f"Failed to authenticate with Odoo: {str(e)}")

    _MAX_RETRIES = 3
    _RETRY_BACKOFF = 1.0  # seconds, doubled each retry

    def _execute(self, model: str, method: str, *args: Any, **kwargs: Any) -> Any:
        """Execute a method on an Odoo v9 model via JSON-RPC with retry on transient errors."""
        last_error: Exception | None = None

        for attempt in range(self._MAX_RETRIES):
            try:
                return self._jsonrpc_call(
                    "object",
                    "execute_kw",
                    self.db,
                    self.uid,
                    self.password,
                    model,
                    method,
                    args,
                    kwargs,
                )
            except (ConnectionError, TimeoutError) as e:
                last_error = e
                if attempt < self._MAX_RETRIES - 1:
                    wait = self._RETRY_BACKOFF * (2**attempt)
                    print(
                        f"Transient error (attempt {attempt + 1}/{self._MAX_RETRIES}), "
                        f"retrying in {wait}s: {e}",
                        file=sys.stderr,
                    )
                    time.sleep(wait)
            except ValueError as e:
                # Check if this is a session/auth error — re-authenticate once
                err_msg = str(e).lower()
                if attempt == 0 and (
                    "session" in err_msg
                    or "access denied" in err_msg
                    or "uid" in err_msg
                ):
                    print(
                        f"Possible session expiry, re-authenticating: {e}",
                        file=sys.stderr,
                    )
                    try:
                        self._connect()
                        continue
                    except Exception:
                        pass
                raise

        raise last_error  # type: ignore[misc]

    def execute_method(self, model: str, method: str, *args: Any, **kwargs: Any) -> Any:
        """
        Execute an arbitrary method on a model

        Args:
            model: The model name (e.g., 'res.partner')
            method: Method name to execute
            *args: Positional arguments to pass to the method
            **kwargs: Keyword arguments to pass to the method

        Returns:
            Result of the method execution
        """
        return self._execute(model, method, *args, **kwargs)

    def get_models(self) -> dict[str, Any]:
        """
        Get a list of all available models in the system

        Returns:
            List of model names

        Examples:
            >>> client = OdooClient(url, db, username, password)
            >>> models = client.get_models()
            >>> print(len(models))
            125
            >>> print(models[:5])
            ['res.partner', 'res.users', 'res.company', 'res.groups', 'ir.model']
        """
        try:
            # Single RPC call instead of search + read
            result = self._execute(
                "ir.model", "search_read", [], {"fields": ["model", "name"]}
            )

            if not result:
                return {
                    "model_names": [],
                    "models_details": {},
                    "error": "No models found",
                }

            # Extract and sort model names alphabetically
            models = sorted([rec["model"] for rec in result])

            # For more detailed information, include the full records
            models_info = {
                "model_names": models,
                "models_details": {
                    rec["model"]: {"name": rec.get("name", "")} for rec in result
                },
            }

            return models_info
        except Exception as e:
            print(f"Error retrieving models: {str(e)}", file=sys.stderr)
            return {"model_names": [], "models_details": {}, "error": str(e)}

    def get_model_info(self, model_name: str) -> dict[str, Any]:
        """
        Get information about a specific model

        Args:
            model_name: Name of the model (e.g., 'res.partner')

        Returns:
            Dictionary with model information

        Examples:
            >>> client = OdooClient(url, db, username, password)
            >>> info = client.get_model_info('res.partner')
            >>> print(info['name'])
            'Contact'
        """
        try:
            result = self._execute(
                "ir.model",
                "search_read",
                [("model", "=", model_name)],
                {"fields": ["name", "model"]},
            )

            if not result:
                return {"error": f"Model {model_name} not found"}

            return result[0]
        except Exception as e:
            print(f"Error retrieving model info: {str(e)}", file=sys.stderr)
            return {"error": str(e)}

    def get_model_fields(self, model_name: str) -> dict[str, Any]:
        """
        Get field definitions for a specific model

        Args:
            model_name: Name of the model (e.g., 'res.partner')

        Returns:
            Dictionary mapping field names to their definitions

        Examples:
            >>> client = OdooClient(url, db, username, password)
            >>> fields = client.get_model_fields('res.partner')
            >>> print(fields['name']['type'])
            'char'
        """
        try:
            fields = self._execute(model_name, "fields_get")
            return fields
        except Exception as e:
            print(f"Error retrieving fields: {str(e)}", file=sys.stderr)
            return {"error": str(e)}

    def discover_model_buttons(self, model_name: str) -> list[dict[str, str]]:
        """
        Discover callable business methods by parsing form view button elements.

        Queries ir.ui.view for form views of the model, then extracts
        <button type="object" name="method_name"/> elements from the XML arch.

        Args:
            model_name: Name of the model (e.g., 'sale.order')

        Returns:
            List of dicts with 'name' and 'string' keys, e.g.:
            [{"name": "action_confirm", "string": "Confirm"}]
        """
        cache_key = f"buttons:{model_name}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            views = self._execute(
                "ir.ui.view",
                "search_read",
                [("model", "=", model_name), ("type", "=", "form")],
                {"fields": ["arch"], "limit": 50},
            )

            if not views:
                return []

            seen = set()
            buttons = []

            MAX_VIEW_SIZE = 500_000  # 500KB — more than sufficient for any Odoo view

            for view in views:
                arch = view.get("arch", "")
                if not arch:
                    continue

                if len(arch) > MAX_VIEW_SIZE:
                    print(
                        f"Skipping oversized view arch ({len(arch)} bytes) for {model_name}",
                        file=sys.stderr,
                    )
                    continue

                try:
                    root = ET.fromstring(arch)
                except ET.ParseError:
                    continue

                for btn in root.iter("button"):
                    btn_type = btn.get("type", "")
                    btn_name = btn.get("name", "")
                    btn_string = btn.get("string", "")

                    # Only object-type buttons are Python method calls
                    if btn_type != "object" or not btn_name:
                        continue

                    # Skip server action references (contain % or are numeric)
                    if "%" in btn_name or btn_name.isdigit():
                        continue

                    if btn_name not in seen:
                        seen.add(btn_name)
                        buttons.append({"name": btn_name, "string": btn_string})

            self._cache.set(cache_key, buttons)
            return buttons
        except Exception as e:
            print(f"discover_model_buttons({model_name}) failed: {e}", file=sys.stderr)
            return []

    def get_state_field_info(self, model_name: str) -> dict[str, Any] | None:
        """
        Get state/stage field information for a model.

        Checks for 'state' (selection) and 'stage_id' (many2one) fields
        using the existing fields_get() call.

        Args:
            model_name: Name of the model (e.g., 'sale.order')

        Returns:
            Dict with state/stage info, or None if neither field exists.
            Example: {"state": {"type": "selection", "string": "Status",
                      "values": [["draft","Draft"], ...]}}
        """
        try:
            fields = self.get_model_fields(model_name)
            if "error" in fields:
                return None

            result = {}

            if "state" in fields:
                state_field = fields["state"]
                if state_field.get("type") == "selection":
                    result["state"] = {
                        "type": "selection",
                        "string": state_field.get("string", "Status"),
                        "values": state_field.get("selection", []),
                    }

            if "stage_id" in fields:
                stage_field = fields["stage_id"]
                if stage_field.get("type") == "many2one":
                    result["stage_id"] = {
                        "type": "many2one",
                        "string": stage_field.get("string", "Stage"),
                        "relation": stage_field.get("relation", ""),
                    }

            return result if result else None
        except Exception as e:
            print(f"get_state_field_info({model_name}) failed: {e}", file=sys.stderr)
            return None

    def discover_workflows(self) -> list[dict[str, Any]]:
        """
        Discover formal Odoo v9 workflows from the workflow engine.

        Queries workflow, workflow.activity, workflow.transition ORM models
        to build a readable representation of formal workflows.

        Returns:
            List of workflow dicts with activities and transitions.
        """
        cached = self._cache.get("workflows")
        if cached is not None:
            return cached

        try:
            # Check if workflow model is accessible
            wf_ids = self._execute("workflow", "search", [], {"limit": 100})
            if not wf_ids:
                return []

            workflows_data = self._execute(
                "workflow", "read", wf_ids, ["name", "osv", "on_create"]
            )

            results = []
            for wf in workflows_data:
                wf_id = wf["id"]
                wf_entry = {
                    "name": wf.get("name", ""),
                    "model": wf.get("osv", ""),
                    "on_create": wf.get("on_create", False),
                    "activities": [],
                    "transitions": [],
                }

                # Get activities for this workflow
                try:
                    act_ids = self._execute(
                        "workflow.activity",
                        "search",
                        [("wkf_id", "=", wf_id)],
                    )
                    if act_ids:
                        activities = self._execute(
                            "workflow.activity",
                            "read",
                            act_ids,
                            [
                                "name",
                                "kind",
                                "flow_start",
                                "flow_stop",
                                "action",
                                "signal_send",
                            ],
                        )
                        wf_entry["activities"] = [
                            {
                                "id": a["id"],
                                "name": a.get("name", ""),
                                "kind": a.get("kind", ""),
                                "flow_start": a.get("flow_start", False),
                                "flow_stop": a.get("flow_stop", False),
                                "action": a.get("action", ""),
                            }
                            for a in activities
                        ]
                except Exception as e:
                    print(
                        f"Failed to fetch activities for workflow {wf_id}: {e}",
                        file=sys.stderr,
                    )

                # Get transitions for this workflow
                try:
                    trans_ids = self._execute(
                        "workflow.transition",
                        "search",
                        [
                            (
                                "act_from",
                                "in",
                                [a["id"] for a in wf_entry["activities"]],
                            )
                        ],
                    )
                    if trans_ids:
                        transitions = self._execute(
                            "workflow.transition",
                            "read",
                            trans_ids,
                            ["act_from", "act_to", "signal", "condition"],
                        )
                        wf_entry["transitions"] = [
                            {
                                "from": (
                                    t.get("act_from", [False, ""])[1]
                                    if isinstance(t.get("act_from"), (list, tuple))
                                    else t.get("act_from", "")
                                ),
                                "to": (
                                    t.get("act_to", [False, ""])[1]
                                    if isinstance(t.get("act_to"), (list, tuple))
                                    else t.get("act_to", "")
                                ),
                                "signal": t.get("signal", ""),
                                "condition": t.get("condition", ""),
                            }
                            for t in transitions
                        ]
                except Exception as e:
                    print(
                        f"Failed to fetch transitions for workflow {wf_id}: {e}",
                        file=sys.stderr,
                    )

                results.append(wf_entry)

            self._cache.set("workflows", results)
            return results
        except Exception as e:
            print(f"discover_workflows() failed: {e}", file=sys.stderr)
            return []

    def discover_state_machines(self) -> list[dict[str, Any]]:
        """
        Find models that have a state selection field (informal state machines).

        Queries ir.model.fields for fields named 'state' with type 'selection',
        then fetches the selection values via fields_get on each model.
        Excludes technical/internal models.

        Returns:
            List of dicts with model name, display name, and state field values.
        """
        cached = self._cache.get("state_machines")
        if cached is not None:
            return cached

        try:
            # Find models with a 'state' selection field
            state_fields = self._execute(
                "ir.model.fields",
                "search_read",
                [("name", "=", "state"), ("ttype", "=", "selection")],
                {"fields": ["model_id"], "limit": 200},
            )

            if not state_fields:
                return []

            # Get model IDs
            model_ids = list(
                {sf["model_id"][0] for sf in state_fields if sf.get("model_id")}
            )

            if not model_ids:
                return []

            # Read model names
            models = self._execute("ir.model", "read", model_ids, ["model", "name"])

            # Filter out technical models
            technical_prefixes = (
                "ir.",
                "base.",
                "bus.",
                "_unknown",
                "base_import.",
                "web_",
            )
            filtered = [
                m for m in models if not m["model"].startswith(technical_prefixes)
            ]

            # Cap to prevent excessive queries
            filtered = filtered[:30]

            results = []
            for model_rec in filtered:
                model_name = model_rec["model"]
                try:
                    fields = self._execute(
                        model_name,
                        "fields_get",
                        ["state"],
                        {"attributes": ["type", "string", "selection"]},
                    )
                    state_info = fields.get("state", {})
                    if state_info.get("type") == "selection":
                        results.append(
                            {
                                "model": model_name,
                                "display_name": model_rec.get("name", ""),
                                "state_field": {
                                    "string": state_info.get("string", "Status"),
                                    "values": state_info.get("selection", []),
                                },
                            }
                        )
                except Exception as e:
                    print(
                        f"Failed to get state info for {model_name}: {e}",
                        file=sys.stderr,
                    )
                    continue

            self._cache.set("state_machines", results)
            return results
        except Exception as e:
            print(f"discover_state_machines() failed: {e}", file=sys.stderr)
            return []

    def search_read(
        self,
        model_name: str,
        domain: list[Any],
        fields: list[str] | None = None,
        offset: int | None = None,
        limit: int | None = None,
        order: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Search for records and read their data in a single call

        Args:
            model_name: Name of the model (e.g., 'res.partner')
            domain: Search domain (e.g., [('is_company', '=', True)])
            fields: List of field names to return (None for all)
            offset: Number of records to skip
            limit: Maximum number of records to return
            order: Sorting criteria (e.g., 'name ASC, id DESC')

        Returns:
            List of dictionaries with the matching records

        Examples:
            >>> client = OdooClient(url, db, username, password)
            >>> records = client.search_read('res.partner', [('is_company', '=', True)], limit=5)
            >>> print(len(records))
            5
        """
        kwargs: dict[str, Any] = {}
        if offset is not None:
            kwargs["offset"] = offset
        if fields is not None:
            kwargs["fields"] = fields
        if limit is not None:
            kwargs["limit"] = limit
        if order is not None:
            kwargs["order"] = order

        return self._execute(model_name, "search_read", domain, **kwargs)

    def read_records(
        self, model_name: str, ids: list[int], fields: list[str] | None = None
    ) -> list[dict[str, Any]]:
        """
        Read data of records by IDs

        Args:
            model_name: Name of the model (e.g., 'res.partner')
            ids: List of record IDs to read
            fields: List of field names to return (None for all)

        Returns:
            List of dictionaries with the requested records

        Examples:
            >>> client = OdooClient(url, db, username, password)
            >>> records = client.read_records('res.partner', [1])
            >>> print(records[0]['name'])
            'YourCompany'
        """
        kwargs: dict[str, Any] = {}
        if fields is not None:
            kwargs["fields"] = fields

        return self._execute(model_name, "read", ids, kwargs)


def load_config() -> dict[str, str]:
    """
    Load Odoo configuration from environment variables, .env file, or config file

    Priority order:
    1. Environment variables already set (e.g. by Claude Desktop, Docker, systemd)
    2. .env file from common locations (does NOT override existing env vars)
    3. JSON config files

    Environment Variables:
        ODOO_CONFIG_DIR: Custom directory to search for .env file

    Returns:
        dict: Configuration dictionary with url, db, username, password
    """
    required_vars = ["ODOO_URL", "ODOO_DB", "ODOO_USERNAME", "ODOO_PASSWORD"]

    # 1. If all required env vars are already set, use them directly
    if all(var in os.environ for var in required_vars):
        print("Using environment variables (already set)", file=sys.stderr)
        return {
            "url": os.environ["ODOO_URL"],
            "db": os.environ["ODOO_DB"],
            "username": os.environ["ODOO_USERNAME"],
            "password": os.environ["ODOO_PASSWORD"],
        }

    # 2. Try to load .env file (does NOT override existing env vars)
    env_paths = []

    custom_config_dir = os.environ.get("ODOO_CONFIG_DIR")
    if custom_config_dir:
        custom_env_path = os.path.join(os.path.expanduser(custom_config_dir), ".env")
        env_paths.append(custom_env_path)

    env_paths.extend(
        [
            ".env",
            os.path.expanduser("~/.config/odoo/.env"),
            os.path.expanduser("~/.env"),
        ]
    )

    for env_path in env_paths:
        expanded_path = os.path.expanduser(env_path)
        if os.path.exists(expanded_path):
            print(f"Loading configuration from: {expanded_path}", file=sys.stderr)
            load_dotenv(dotenv_path=expanded_path, override=False)
            break

    # Check env vars again (may have been populated by .env file)
    if all(var in os.environ for var in required_vars):
        return {
            "url": os.environ["ODOO_URL"],
            "db": os.environ["ODOO_DB"],
            "username": os.environ["ODOO_USERNAME"],
            "password": os.environ["ODOO_PASSWORD"],
        }

    # 3. Fall back to JSON config files
    config_paths = [
        "./odoo_config.json",
        os.path.expanduser("~/.config/odoo/config.json"),
        os.path.expanduser("~/.odoo_config.json"),
    ]

    for path in config_paths:
        expanded_path = os.path.expanduser(path)
        if os.path.exists(expanded_path):
            print(f"Loading configuration from: {expanded_path}", file=sys.stderr)
            with open(expanded_path, "r") as f:
                cfg = json.load(f)
            if not isinstance(cfg, dict):
                raise ValueError(
                    f"Config file {expanded_path} must contain a JSON object, "
                    f"got {type(cfg).__name__}"
                )
            missing = {"url", "db", "username", "password"} - set(cfg.keys())
            if missing:
                raise ValueError(
                    f"Config file {expanded_path} is missing required keys: "
                    f"{', '.join(sorted(missing))}"
                )
            return cfg

    raise FileNotFoundError(
        "No Odoo configuration found. Please create a .env file, set environment variables, or create an odoo_config.json file.\n"
        "Searched for .env in:\n  " + "\n  ".join(env_paths) + "\n"
        "Searched for JSON config in:\n  " + "\n  ".join(config_paths)
    )


_odoo_client_instance: OdooClient | None = None
_odoo_client_lock = threading.Lock()


def get_odoo_client() -> OdooClient:
    """
    Get a configured Odoo v9 client singleton (JSON-RPC only)

    Thread-safe. The client is created and authenticated once on the first call,
    then reused for all subsequent calls (config is read once, session is reused).

    Environment variables:
        ODOO_URL: Odoo server URL
        ODOO_DB: Database name
        ODOO_USERNAME: Login username
        ODOO_PASSWORD: Login password

    Returns:
        OdooClient: A configured Odoo client instance
    """
    global _odoo_client_instance
    if _odoo_client_instance is not None:
        return _odoo_client_instance

    with _odoo_client_lock:
        # Double-check after acquiring lock
        if _odoo_client_instance is not None:
            return _odoo_client_instance

        config = load_config()

        password = config.get("password") or os.environ.get("ODOO_PASSWORD")
        if not password:
            raise ValueError(
                "ODOO_PASSWORD is required but not set. "
                "Set it via environment variable, .env file, or odoo_config.json."
            )

        # Get additional options from environment variables
        timeout = int(os.environ.get("ODOO_TIMEOUT", "30"))
        verify_ssl = os.environ.get("ODOO_VERIFY_SSL", "1").lower() in [
            "1",
            "true",
            "yes",
        ]

        # Print configuration once at startup
        print("Odoo v9 client configuration:", file=sys.stderr)
        print(f"  URL: {config['url']}", file=sys.stderr)
        print(f"  Database: {config['db']}", file=sys.stderr)
        print(f"  Username: {config['username']}", file=sys.stderr)
        print("  API: JSON-RPC", file=sys.stderr)
        print(
            f"  Auth: Password ({'set' if password else 'NOT SET'})",
            file=sys.stderr,
        )
        print(f"  Timeout: {timeout}s", file=sys.stderr)
        print(f"  Verify SSL: {verify_ssl}", file=sys.stderr)

        _odoo_client_instance = OdooClient(
            url=config["url"],
            db=config["db"],
            username=config["username"],
            password=password,
            timeout=timeout,
            verify_ssl=verify_ssl,
        )
        return _odoo_client_instance
