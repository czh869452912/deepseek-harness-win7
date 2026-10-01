"""
Creative Mode Cordis Inspection & Runtime Management Tools
matching reference/packages/extensions/tool-cordis
"""

import json
from typing import Any, Dict, List, Optional
from dsh.cordis.plugin import Plugin
from dsh.core.session.json import UNDEFINED
from dsh.extensions.inspect_providers import host_inspect_providers


class CordisManagerPlugin(Plugin):
    """
    Plugin `@deepseek-ai/dsh-tool-cordis` & `@deepseek-ai/dsh-cordis-manager`:
    Creative Mode (创造模式) official Cordis inspection, define, run, stop, and undefine tools.
    """

    id = "tool-cordis"
    name = "@deepseek-ai/dsh-tool-cordis"
    inject = ["tools", "systemPrompt", "dynamicCordisRunner", "cordisInspect"]

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.runner = None

    def apply(self, ctx: Any) -> None:
        tools_service = ctx.get("tools")
        if not tools_service:
            return

        self.runner = ctx.get("dynamicCordisRunner")
        for provider in host_inspect_providers(ctx):
            ctx.effect(lambda provider=provider: ctx.get('cordisInspect').register(provider),
                       'tool-cordis: inspect ' + provider['manifest']['id'])
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
            if operation == 'inspect_list':
                return dict(providers=ctx.get('cordisInspect').list())
            if agent is None:
                raise ValueError('Cordis dynamic tools require an Agent-backed session')
            runner = ctx.get('dynamicCordisRunner')
            if operation == 'inspect_query':
                data = await ctx.get('cordisInspect').query(args['platform'], args['provider'], args['method'],
                    args.get('input', UNDEFINED), agent, signal)
                return dict(platform=args['platform'], provider=args['provider'], method=args['method'], data=data)
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
            "description": "List the actual Host and synchronized Client Inspect providers, their read-only methods and input/output schemas. Select an exact provider and method from this directory before querying.",
            "parameters": {"type": "object", "properties": {}},
            "execute": lambda args, _exec: canonical_call(self.handle_inspect_list, args, _exec),
            "output": json_output({"type": "object"}, text_json),
        })

        # 2. cordis_inspect_query
        tools_service.register_tool({
            "name": "cordis_inspect_query",
            "description": "Run a declared read-only Inspect query. Host queries run locally; Client queries wait for the first valid page response or cancellation. Read Service/Event contracts from their catalog; this tool does not invoke business service methods.",
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

    async def handle_inspect_list(self):
        return dict(providers=self.ctx.get('cordisInspect').list())

    async def handle_inspect_query(self, platform, provider, method, input=UNDEFINED, agent=None, signal=None):
        if agent is None:
            raise ValueError('Cordis dynamic tools require an Agent-backed session')
        data = await self.ctx.get('cordisInspect').query(platform, provider, method, input, agent, signal)
        return dict(platform=platform, provider=provider, method=method, data=data)
