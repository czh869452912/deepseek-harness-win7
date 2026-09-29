"""
Creative Mode Cordis Inspection & Runtime Management Tools
matching reference/packages/extensions/tool-cordis
"""

import json
from typing import Any, Dict, List, Optional
from dsh.cordis.plugin import Plugin


class CordisManagerPlugin(Plugin):
    """
    Plugin `@deepseek-ai/dsh-tool-cordis` & `@deepseek-ai/dsh-cordis-manager`:
    Creative Mode (创造模式) official Cordis inspection, define, run, stop, and undefine tools.
    """

    id = "tool-cordis"
    name = "@deepseek-ai/dsh-tool-cordis"
    inject = ["tools", "systemPrompt", "dynamicCordisRunner"]

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.runner = None

    def apply(self, ctx: Any) -> None:
        tools_service = ctx.get("tools")
        if not tools_service:
            return

        self.runner = ctx.get("dynamicCordisRunner")
        ctx.effect(lambda: ctx.get("systemPrompt").section(dict(name="tool:cordis", order=700, text=self.on_prompt_assemble(""))), "tool:cordis prompt")

        def json_output(schema: Dict[str, Any], render: Any, meta: Any = None) -> Dict[str, Any]:
            result = {"schema": schema, "render": render}
            if meta is not None:
                result["presentationMeta"] = meta
            return result

        def text_json(_args: Any, value: Any) -> List[Dict[str, str]]:
            return [{"type": "text", "text": json.dumps(value, indent=2, ensure_ascii=False)}]

        async def canonical_call(fn, args, execution):
            agent = getattr(execution, 'agent', None)
            signal = getattr(execution, 'signal', None)
            operation = fn if isinstance(fn, str) else fn.__name__.replace('handle_', '')
            if operation in ('inspect_list', 'inspect_query'):
                value = await fn(**args)
                return json.loads(value)
            if agent is None:
                raise ValueError('Cordis dynamic tools require an Agent-backed session')
            runner = ctx.get('dynamicCordisRunner')
            if operation == 'define':
                return runner.define(dict(args, sessionId=agent.id))
            if operation == 'run':
                return await runner.run(agent, signal=signal, **args)
            if operation in ('stop', 'undefine'):
                return await getattr(runner, operation)(agent, **args)
            if operation == 'inspect_self':
                pid, package = args.get('pluginId'), args.get('packageId')
                if pid is None:
                    return dict(mode='plugins', plugins=runner.listPlugins(agent))
                if package is None:
                    found = runner.inspectPlugin(agent, pid)
                    if found is None:
                        raise ValueError('dynamic plugin is not owned by this session')
                    return dict(mode='plugin', **found)
                return dict(mode='package', **runner.inspectPackage(agent, pid, package))
            raise ValueError('unknown Cordis operation')

        # 1. cordis_inspect_list
        tools_service.register_tool({
            "name": "cordis_inspect_list",
            "description": "List every Cordis Inspect Provider currently known to the Host (Service, Event, Builtin, Tool).",
            "parameters": {"type": "object", "properties": {}},
            "execute": lambda args, _exec: canonical_call(self.handle_inspect_list, args, _exec),
            "output": json_output({"type": "object"}, text_json),
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
                    "input": {"description": "Optional query input object"},
                },
                "required": ["platform", "provider", "method"],
            },
            "execute": lambda args, _exec: canonical_call(self.handle_inspect_query, args, _exec),
            "output": json_output({"type": "object"}, text_json),
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
            "execute": lambda args, _exec: canonical_call("inspect_self", args, _exec),
            "output": json_output({"type": "object"}, text_json),
        })

        # 4. cordis_define
        tools_service.register_tool({
            "name": "cordis_define",
            "description": "Define an immutable Cordis Package with Python Host and JavaScript Client code. Host code must define a callable named plugin.",
            "parameters": {
                "type": "object",
                "properties": {
                    "plugin": {
                        "oneOf": [
                            {"type": "object", "additionalProperties": False,
                             "properties": {"kind": {"type": "string", "const": "new"},
                                             "idPrefix": {"type": "string"}},
                             "required": ["kind", "idPrefix"]},
                            {"type": "object", "additionalProperties": False,
                             "properties": {"kind": {"type": "string", "const": "existing"},
                                             "pluginId": {"type": "string"}},
                             "required": ["kind", "pluginId"]},
                        ],
                        "description": "{ kind: 'new', idPrefix: 'foo' } or { kind: 'existing', pluginId: 'foo-101' }",
                    },
                    "name": {"type": "string", "description": "Short, readable Package name"},
                    "purpose": {"type": "string", "description": "User-facing description of the Package purpose"},
                    "code": {
                        "type": "object", "additionalProperties": False,
                        "properties": {
                            "host": {"type": "string", "description": "Host-half plugin code function body"},
                            "client": {"type": "string", "description": "Client-half plugin code function body"},
                        },
                    },
                },
                "required": ["plugin", "name", "purpose", "code"],
            },
            "execute": lambda args, _exec: canonical_call("define", args, _exec),
            "output": json_output({"type": "object"}, text_json,
                                   lambda _args, value: {"pluginId": value.get("pluginId"), "packageId": value.get("packageId")}),
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
            "execute": lambda args, _exec: canonical_call("run", args, _exec),
            "output": json_output({"type": "object"}, text_json,
                                   lambda _args, value: {k: value[k] for k in ("pluginId", "packageId", "pluginRunId") if k in value}),
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
            "execute": lambda args, _exec: canonical_call("stop", args, _exec),
            "output": json_output({"type": "object"}, text_json),
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
            "execute": lambda args, _exec: canonical_call("undefine", args, _exec),
            "output": json_output({"type": "object"}, text_json),
        })

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
