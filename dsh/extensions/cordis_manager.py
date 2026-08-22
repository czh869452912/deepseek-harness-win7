"""
Creative Mode Cordis Inspection & Runtime Management Tools
matching reference/packages/extensions/tool-cordis
"""

import json
import uuid
from typing import Any, Dict, List, Optional
import yaml
from dsh.cordis.plugin import Plugin


class DynamicPluginPackage:
    def __init__(
        self,
        package_id: str,
        name: str,
        purpose: str,
        code_host: Optional[str] = None,
        code_client: Optional[str] = None,
    ):
        self.package_id = package_id
        self.name = name
        self.purpose = purpose
        self.code_host = code_host
        self.code_client = code_client
        self.has_host_half = bool(code_host)
        self.has_client_half = bool(code_client)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "packageId": self.package_id,
            "name": self.name,
            "purpose": self.purpose,
            "hasHostHalf": self.has_host_half,
            "hasClientHalf": self.has_client_half,
            "code": {
                "host": self.code_host,
                "client": self.code_client,
            },
        }


class DynamicPluginEntity:
    def __init__(self, plugin_id: str, name: str):
        self.plugin_id = plugin_id
        self.name = name
        self.packages: Dict[str, DynamicPluginPackage] = {}
        self.current_package_id: Optional[str] = None
        self.next_package_id: Optional[str] = None
        self.status: str = "defined"  # defined, running, stopped, awaiting-approval
        self.active_run_id: Optional[str] = None

    def add_package(self, pkg: DynamicPluginPackage) -> None:
        self.packages[pkg.package_id] = pkg
        self.next_package_id = pkg.package_id

    def to_summary(self) -> Dict[str, Any]:
        res: Dict[str, Any] = {
            "pluginId": self.plugin_id,
            "name": self.name,
            "packageCount": len(self.packages),
            "state": self.status,
        }
        if self.current_package_id:
            res["currentPackageId"] = self.current_package_id
        if self.next_package_id:
            res["nextPackageId"] = self.next_package_id
        if self.active_run_id:
            res["activeRun"] = {
                "pluginRunId": self.active_run_id,
                "packageId": self.current_package_id or self.next_package_id,
            }
        return res


class DynamicCordisRunnerService:
    """Manages session-owned dynamic Cordis plugins and packages."""

    def __init__(self, ctx: Any):
        self.ctx = ctx
        self.plugins: Dict[str, DynamicPluginEntity] = {}
        self._seq: int = 100

    def define(
        self,
        plugin_spec: Dict[str, Any],
        name: str,
        purpose: str,
        code: Dict[str, Any],
    ) -> Dict[str, Any]:
        kind = plugin_spec.get("kind", "new")
        if kind == "new":
            prefix = plugin_spec.get("idPrefix", "mod")[:6].lower()
            self._seq += 1
            plugin_id = f"{prefix}-{self._seq}"
            entity = DynamicPluginEntity(plugin_id=plugin_id, name=name)
            self.plugins[plugin_id] = entity
        else:
            plugin_id = plugin_spec.get("pluginId", "")
            if plugin_id not in self.plugins:
                entity = DynamicPluginEntity(plugin_id=plugin_id, name=name)
                self.plugins[plugin_id] = entity
            else:
                entity = self.plugins[plugin_id]

        pkg_num = len(entity.packages) + 1
        pkg_id = f"pkg-{pkg_num:03d}"
        package = DynamicPluginPackage(
            package_id=pkg_id,
            name=name,
            purpose=purpose,
            code_host=code.get("host"),
            code_client=code.get("client"),
        )
        entity.add_package(package)

        return {
            "pluginId": plugin_id,
            "packageId": pkg_id,
            "name": name,
            "purpose": purpose,
            "hasHostHalf": package.has_host_half,
            "hasClientHalf": package.has_client_half,
        }

    def run(self, plugin_id: str, package_id: str, mode: str = "run") -> Dict[str, Any]:
        if plugin_id not in self.plugins:
            return {"ok": False, "message": f"Plugin '{plugin_id}' not found"}
        entity = self.plugins[plugin_id]
        if package_id not in entity.packages:
            return {"ok": False, "message": f"Package '{package_id}' not found in plugin '{plugin_id}'"}

        run_id = f"run-{uuid.uuid4().hex[:8]}"
        entity.current_package_id = package_id
        entity.next_package_id = package_id
        entity.active_run_id = run_id
        entity.status = "running"

        return {
            "ok": True,
            "status": "running",
            "pluginId": plugin_id,
            "packageId": package_id,
            "pluginRunId": run_id,
            "mode": mode,
            "currentPackageId": package_id,
            "nextPackageId": package_id,
            "host": {
                "status": "running",
                "provides": [],
                "waitingFor": [],
            },
            "client": {
                "status": "running" if entity.packages[package_id].has_client_half else "absent",
                "waitingFor": [],
            },
        }

    def stop(self, plugin_id: str) -> Dict[str, Any]:
        if plugin_id not in self.plugins:
            return {"ok": False, "reason": "not-found", "message": f"Plugin '{plugin_id}' not found"}
        entity = self.plugins[plugin_id]
        entity.status = "stopped"
        entity.active_run_id = None
        return {"ok": True, "pluginId": plugin_id}

    def undefine(self, plugin_id: str) -> Dict[str, Any]:
        if plugin_id not in self.plugins:
            return {"ok": False, "reason": "not-found", "message": f"Plugin '{plugin_id}' not found"}
        was_running = self.plugins[plugin_id].status == "running"
        del self.plugins[plugin_id]
        return {"ok": True, "pluginId": plugin_id, "wasRunning": was_running}

    def list_plugins(self) -> List[Dict[str, Any]]:
        return [entity.to_summary() for entity in self.plugins.values()]

    def inspect_plugin(self, plugin_id: str) -> Optional[Dict[str, Any]]:
        if plugin_id not in self.plugins:
            return None
        entity = self.plugins[plugin_id]
        res = entity.to_summary()
        res["packages"] = [pkg.to_dict() for pkg in entity.packages.values()]
        return res

    def inspect_package(self, plugin_id: str, package_id: str) -> Optional[Dict[str, Any]]:
        if plugin_id not in self.plugins:
            return None
        entity = self.plugins[plugin_id]
        if package_id not in entity.packages:
            return None
        pkg = entity.packages[package_id]
        return {
            "mode": "package",
            "plugin": entity.to_summary(),
            "packageId": package_id,
            "name": pkg.name,
            "purpose": pkg.purpose,
            "code": {
                "host": pkg.code_host,
                "client": pkg.code_client,
            },
            "runtime": {
                "state": entity.status,
                "host": {"status": "running" if entity.status == "running" else "stopped", "provides": [], "waitingFor": []},
                "client": {"status": "running" if entity.status == "running" and pkg.has_client_half else "absent", "waitingFor": []},
            },
        }


class CordisManagerPlugin(Plugin):
    """
    Plugin `@deepseek-ai/dsh-tool-cordis` & `@deepseek-ai/dsh-cordis-manager`:
    Creative Mode (创造模式) official Cordis inspection, define, run, stop, and undefine tools.
    """

    id = "tool-cordis"
    name = "@deepseek-ai/dsh-tool-cordis"
    inject = ["tools"]

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.runner: Optional[DynamicCordisRunnerService] = None

    def apply(self, ctx: Any) -> None:
        tools_service = ctx.get("tools")
        if not tools_service:
            return

        self.runner = DynamicCordisRunnerService(ctx)
        ctx.set_service("dynamicCordisRunner", self.runner)

        # 1. cordis_inspect_list
        tools_service.register_tool({
            "name": "cordis_inspect_list",
            "description": "List every Cordis Inspect Provider currently known to the Host (Service, Event, Builtin, Tool).",
            "parameters": {"type": "object", "properties": {}},
            "execute": self.handle_inspect_list,
        })

        # 2. cordis_inspect_query
        tools_service.register_tool({
            "name": "cordis_inspect_query",
            "description": "Run a read-only query declared by an Inspect Provider (e.g. Service methods, Event contracts, Tool schemas).",
            "parameters": {
                "type": "object",
                "properties": {
                    "platform": {"type": "string", "enum": ["host", "client"], "description": "Runtime platform that owns the Provider"},
                    "provider": {"type": "string", "description": "Exact Provider ID (Service, Event, Builtin, Tool)"},
                    "method": {"type": "string", "description": "Exact method name (e.g. listService, listEvents, listBuiltins, listTools)"},
                    "input": {"type": "object", "description": "Optional query input object"},
                },
                "required": ["platform", "provider", "method"],
            },
            "execute": self.handle_inspect_query,
        })

        # 3. cordis_inspect_self
        tools_service.register_tool({
            "name": "cordis_inspect_self",
            "description": "Inspect dynamic Cordis objects owned by the current session (Plugin summaries, Package source & diagnostics).",
            "parameters": {
                "type": "object",
                "properties": {
                    "pluginId": {"type": "string", "description": "Stable Plugin ID; omit to list every dynamic Plugin"},
                    "packageId": {"type": "string", "description": "Exact immutable Package ID owned by pluginId"},
                },
            },
            "execute": self.handle_inspect_self,
        })

        # 4. cordis_define
        tools_service.register_tool({
            "name": "cordis_define",
            "description": "Define an immutable Cordis Package with host/client JavaScript code body.",
            "parameters": {
                "type": "object",
                "properties": {
                    "plugin": {
                        "type": "object",
                        "description": "{ kind: 'new', idPrefix: 'foo' } or { kind: 'existing', pluginId: 'foo-101' }",
                    },
                    "name": {"type": "string", "description": "Short, readable Package name"},
                    "purpose": {"type": "string", "description": "User-facing description of the Package purpose"},
                    "code": {
                        "type": "object",
                        "properties": {
                            "host": {"type": "string", "description": "Host-half plugin code function body"},
                            "client": {"type": "string", "description": "Client-half plugin code function body"},
                        },
                    },
                },
                "required": ["plugin", "name", "purpose", "code"],
            },
            "execute": self.handle_define,
        })

        # 5. cordis_run
        tools_service.register_tool({
            "name": "cordis_run",
            "description": "Activate one exact Package of a dynamic Plugin (mode: 'run' or 'update').",
            "parameters": {
                "type": "object",
                "properties": {
                    "pluginId": {"type": "string", "description": "Stable Plugin ID returned by cordis_define"},
                    "packageId": {"type": "string", "description": "Exact immutable Package ID to activate"},
                    "mode": {"type": "string", "enum": ["run", "update"], "description": "Activation mode"},
                },
                "required": ["pluginId", "packageId", "mode"],
            },
            "execute": self.handle_run,
        })

        # 6. cordis_stop
        tools_service.register_tool({
            "name": "cordis_stop",
            "description": "Stop the current run of a dynamic Plugin, retaining its Package definitions.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pluginId": {"type": "string", "description": "Stable dynamic Plugin ID to stop"},
                },
                "required": ["pluginId"],
            },
            "execute": self.handle_stop,
        })

        # 7. cordis_undefine
        tools_service.register_tool({
            "name": "cordis_undefine",
            "description": "Permanently remove a dynamic Plugin and all of its Packages from the current session.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pluginId": {"type": "string", "description": "Stable dynamic Plugin ID to remove"},
                },
                "required": ["pluginId"],
            },
            "execute": self.handle_undefine,
        })

        # Backward compatibility aliases
        tools_service.register(
            name="cordis_list_plugins",
            description="[Alias for cordis_inspect_self] List all dynamic and static plugins.",
            parameters={"type": "object", "properties": {}},
            handler=self.handle_list_plugins_compat,
        )

        tools_service.register(
            name="cordis_inspect_context",
            description="[Alias for cordis_inspect_query] Inspect mounted Cordis services and system status.",
            parameters={"type": "object", "properties": {}},
            handler=self.handle_inspect_context_compat,
        )

        tools_service.register(
            name="cordis_unload_plugin",
            description="[Alias for cordis_stop] Unload or stop an active plugin.",
            parameters={
                "type": "object",
                "properties": {
                    "plugin_id": {"type": "string", "description": "ID of the plugin to unload"},
                },
                "required": ["plugin_id"],
            },
            handler=self.handle_unload_plugin_compat,
        )

        tools_service.register(
            name="cordis_dump_config",
            description="Dump active Cordis plugin composition configuration tree in YAML format.",
            parameters={"type": "object", "properties": {}},
            handler=self.handle_dump_config_compat,
        )

        ctx.on("agent/prompt-assemble", self.on_prompt_assemble)

    def on_prompt_assemble(self, prompt: str) -> str:
        cordis_prompt = (
            "\n\n[Creative Mode / Cordis Architecture Active]\n"
            "You are running in Creative Mode (创造模式) powered by Cordis 'Everything is a Plugin' architecture.\n"
            "You have access to `cordis_inspect_list`, `cordis_inspect_query`, `cordis_inspect_self`, `cordis_define`, `cordis_run`, `cordis_stop`, and `cordis_undefine`.\n"
            "You can inspect active plugins, query Service/Event/Tool schemas, define dynamic plugins, and author custom presets.\n"
        )
        return prompt + cordis_prompt

    async def handle_inspect_list(self) -> str:
        providers = [
            {
                "id": "Service",
                "description": "Progressive Host Service discovery: compact capability/signature directory, then one exact coding contract.",
                "methods": [{"name": "listService", "description": "List all registered host services and signatures"}],
            },
            {
                "id": "Event",
                "description": "Progressive Host Event discovery: compact listener directory, then one exact event contract.",
                "methods": [{"name": "listEvents", "description": "List all registered host events and dispatch modes"}],
            },
            {
                "id": "Builtin",
                "description": "Plain-JavaScript symbols and standard utilities available to a dynamic Host half.",
                "methods": [{"name": "listBuiltins", "description": "List standard built-in modules and symbols"}],
            },
            {
                "id": "Tool",
                "description": "Tools visible to the requesting Agent, including scoped and dynamic registrations.",
                "methods": [{"name": "listTools", "description": "Return every Tool schema currently callable by this Agent"}],
            },
        ]
        return json.dumps({"providers": providers}, indent=2, ensure_ascii=False)

    async def handle_inspect_query(
        self,
        platform: str,
        provider: str,
        method: str,
        input: Optional[Dict[str, Any]] = None,
    ) -> str:
        ctx = self.ctx
        inp = input or {}
        if provider == "Service":
            services = list(ctx._services.keys()) if hasattr(ctx, "_services") else []
            if hasattr(ctx, "reflect") and hasattr(ctx.reflect, "store"):
                services.extend(list(ctx.reflect.store.keys()))
            services = sorted(list(set(services)))
            srv_name = inp.get("service")
            if not srv_name:
                return json.dumps({"services": services}, indent=2, ensure_ascii=False)
            instance = ctx.get(srv_name)
            methods = [m for m in dir(instance) if not m.startswith("_") and callable(getattr(instance, m, None))]
            return json.dumps({"service": srv_name, "methods": methods}, indent=2, ensure_ascii=False)

        elif provider == "Event":
            events = ["turn/start", "turn/end", "step/start", "step/end", "agent/status", "goal/change", "tools/pre-execute", "tools/post-execute", "internal/plugin", "internal/status", "internal/service", "internal/config", "internal/update", "internal/get", "internal/set"]
            evt_name = inp.get("event")
            if not evt_name:
                return json.dumps({"events": events}, indent=2, ensure_ascii=False)
            return json.dumps({"event": evt_name, "mode": "waterfall" if ("pre-" in evt_name or "internal/" in evt_name) else "emit"}, indent=2, ensure_ascii=False)

        elif provider == "Builtin":
            return json.dumps({"builtins": ["json", "time", "os", "math", "re", "uuid"]}, indent=2, ensure_ascii=False)

        elif provider == "Tool":
            tools_svc = ctx.get("tools")
            schemas = tools_svc.get_tool_definitions() if (tools_svc and hasattr(tools_svc, "get_tool_definitions")) else []
            return json.dumps({"tools": schemas}, indent=2, ensure_ascii=False)

        return json.dumps({"error": f"Unknown provider '{provider}'"}, indent=2, ensure_ascii=False)

    async def handle_inspect_self(
        self,
        pluginId: Optional[str] = None,
        packageId: Optional[str] = None,
    ) -> str:
        if not self.runner:
            return json.dumps({"error": "Runner not initialized"}, indent=2)

        if not pluginId:
            plugins = self.runner.list_plugins()
            return json.dumps({"mode": "plugins", "plugins": plugins}, indent=2, ensure_ascii=False)

        if not packageId:
            plugin = self.runner.inspect_plugin(pluginId)
            if not plugin:
                return json.dumps({"error": f"Plugin '{pluginId}' not found"}, indent=2)
            return json.dumps({"mode": "plugin", **plugin}, indent=2, ensure_ascii=False)

        pkg = self.runner.inspect_package(pluginId, packageId)
        if not pkg:
            return json.dumps({"error": f"Package '{packageId}' not found in plugin '{pluginId}'"}, indent=2)
        return json.dumps(pkg, indent=2, ensure_ascii=False)

    async def handle_define(
        self,
        plugin: Dict[str, Any],
        name: str,
        purpose: str,
        code: Dict[str, Any],
    ) -> str:
        if not self.runner:
            return json.dumps({"error": "Runner not initialized"}, indent=2)
        res = self.runner.define(plugin_spec=plugin, name=name, purpose=purpose, code=code)
        return json.dumps(res, indent=2, ensure_ascii=False)

    async def handle_run(self, pluginId: str, packageId: str, mode: str = "run") -> str:
        if not self.runner:
            return json.dumps({"error": "Runner not initialized"}, indent=2)
        res = self.runner.run(plugin_id=pluginId, package_id=packageId, mode=mode)
        return json.dumps(res, indent=2, ensure_ascii=False)

    async def handle_stop(self, pluginId: str) -> str:
        if not self.runner:
            return json.dumps({"error": "Runner not initialized"}, indent=2)
        res = self.runner.stop(plugin_id=pluginId)
        return json.dumps(res, indent=2, ensure_ascii=False)

    async def handle_undefine(self, pluginId: str) -> str:
        if not self.runner:
            return json.dumps({"error": "Runner not initialized"}, indent=2)
        res = self.runner.undefine(plugin_id=pluginId)
        return json.dumps(res, indent=2, ensure_ascii=False)

    # Legacy compat handlers
    def handle_list_plugins_compat(self, ctx: Optional[Any] = None) -> str:
        c = ctx or self.ctx
        if not c:
            return "Error: Context unavailable"
        plugins = c.list_plugins() if hasattr(c, "list_plugins") else []
        return json.dumps(plugins, indent=2, ensure_ascii=False)

    def handle_inspect_context_compat(self, ctx: Optional[Any] = None) -> str:
        c = ctx or self.ctx
        if not c:
            return "Error: Context unavailable"
        services = list(c._services.keys()) if hasattr(c, "_services") else []
        plugins = [p["id"] for p in c.list_plugins()] if hasattr(c, "list_plugins") else []
        return json.dumps({"services": services, "plugins": plugins}, indent=2, ensure_ascii=False)

    def handle_unload_plugin_compat(self, plugin_id: str = "", pluginId: str = "", ctx: Optional[Any] = None) -> str:
        pid = plugin_id or pluginId
        if not pid:
            return "Error: plugin_id parameter is required"
        if self.runner and pid in self.runner.plugins:
            res = self.runner.stop(plugin_id=pid)
            if res.get("ok"):
                return f"Plugin '{pid}' successfully unloaded."
        c = ctx or self.ctx
        if not c:
            return "Error: Context unavailable"
        success = c.unload_plugin(pid) if hasattr(c, "unload_plugin") else False
        if success:
            return f"Plugin '{pid}' successfully unloaded."
        return f"Plugin '{pid}' not found or could not be unloaded."

    def handle_dump_config_compat(self, ctx: Optional[Any] = None) -> str:
        c = ctx or self.ctx
        if not c:
            return "Error: Context unavailable"
        plugins = c.list_plugins() if hasattr(c, "list_plugins") else []
        dump_data = [{"id": p.get("id"), "name": p.get("name"), "config": p.get("config")} for p in plugins]
        return yaml.dump(dump_data, allow_unicode=True)
