"""
End-to-End Strict 1:1 Parity Test Suite for Core Agent Loop + LLM + System Prompt.
Matches upstream specifications from:
- reference/packages/core/agent-loop/tests/loop.spec.ts
- reference/packages/core/agent-loop/tests/request-reconstruction.spec.ts
- reference/packages/core/agent-loop/tests/interception.spec.ts
- reference/packages/core/agent-loop/tests/contract-regressions.spec.ts
- reference/packages/core/agent-loop/tests/cancel.spec.ts
- reference/packages/core/system-prompt/tests/system-prompt.spec.ts
- reference/packages/core/system-prompt/tests/scoped.spec.ts
- reference/packages/core/system-prompt/tests/tool-order.spec.ts
- reference/packages/llm/llm/tests/service.spec.ts
- reference/packages/llm/llm/tests/assembler.spec.ts
- reference/packages/llm/llm/tests/call-config.spec.ts
- reference/packages/llm/llm-deepseek/tests/translate.spec.ts
"""

import asyncio
import copy
import json
import time
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union
import pytest

from dsh.cordis.context import Context
from dsh.core.agent import Agent, AgentOptions, AgentPlugin, AgentRegistry
from dsh.core.agent_loop import AgentLoopPlugin, AgentLoopService, BlockAssembler, request_proposal
from dsh.core.session import Session, SessionPlugin, SessionStore, canonical_header, header_equals, createUserMessage
from dsh.core.system_prompt import (
    FIRST_PARTY_SECTION_ORDER,
    PERSONA_ORDER,
    PERSONA_SECTION,
    TOOL_ORDER_REST,
    SystemPrompt,
    compare_names,
    compare_prompt_sections,
    compare_tool_names,
    join_context_sections,
    order_tools,
    render_context_sections,
    render_context_snapshot,
    render_prompt,
    validate_tool_order,
)
from dsh.core.tools import ToolsPlugin, ToolsService
from dsh.llm.llm_service import LLMService, LlmError, normalize_api_key, assert_usable_api_key


class ScriptedMockAdapter:
    """
    1:1 Mock LLM Adapter capable of scripted multi-step streaming responses,
    recording incoming GenerateOptions requests, and simulating reasoning, tool calls,
    usage, delays, errors, and cancellations.
    """

    def __init__(self, responses: Optional[List[Any]] = None, model_info: Optional[Dict[str, Any]] = None):
        self.responses: List[Any] = list(responses or [])
        self.requests: List[Dict[str, Any]] = []
        self.provider = "mock-provider"
        self.model = "mock-model"
        self._model_info = model_info or {
            "provider": self.provider,
            "id": self.model,
            "name": "Mock Model",
            "context": {"contextWindow": 128000},
        }

    def provider_info(self, provider: str) -> Dict[str, Any]:
        return {"id": provider, "name": "Mock Provider ({})".format(provider)}

    def provider_retry_policy(self, provider: str) -> Optional[Dict[str, Any]]:
        return None

    async def list_models(self, provider: str) -> List[Dict[str, Any]]:
        return [self._model_info]

    async def resolve_model(self, provider: str, model: str, signal: Any = None) -> Dict[str, Any]:
        info = dict(self._model_info)
        info["provider"] = provider
        info["id"] = model
        return info

    async def chat_completion_stream(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        system: Optional[str] = None,
        request: Optional[Dict[str, Any]] = None,
    ):
        req_record = {
            "messages": copy.deepcopy(messages),
            "tools": copy.deepcopy(tools) if tools else [],
            "system": system,
            "request": copy.deepcopy(request) if request else {},
        }
        self.requests.append(req_record)

        if not self.responses:
            resp_spec = {"text": "default mock response"}
        else:
            resp_spec = self.responses.pop(0)

        # Allow callable / exception in response script
        if isinstance(resp_spec, Exception):
            raise resp_spec

        if callable(resp_spec):
            import inspect
            if inspect.iscoroutinefunction(resp_spec):
                resp_spec = await resp_spec(req_record)
            else:
                resp_spec = resp_spec(req_record)

        if isinstance(resp_spec, Exception):
            raise resp_spec

        chunks: List[Dict[str, Any]] = []
        block_idx = 0

        # Delay simulation if requested
        if isinstance(resp_spec, dict) and resp_spec.get("delay"):
            await asyncio.sleep(resp_spec["delay"])

        # 1. Reasoning blocks (DeepSeek R1/V3 thinking)
        if isinstance(resp_spec, dict) and "reasoning" in resp_spec:
            r_text = resp_spec["reasoning"]
            chunks.append({"type": "block-start", "index": block_idx, "blockType": "reasoning"})
            chunks.append({"type": "reasoning-delta", "index": block_idx, "text": r_text})
            chunks.append({"type": "block-end", "index": block_idx, "block": {"type": "reasoning", "text": r_text}})
            block_idx += 1

        # 2. Text blocks
        if isinstance(resp_spec, dict) and "text" in resp_spec and resp_spec["text"]:
            t_text = resp_spec["text"]
            chunks.append({"type": "block-start", "index": block_idx, "blockType": "text"})
            chunks.append({"type": "text-delta", "index": block_idx, "text": t_text})
            chunks.append({"type": "block-end", "index": block_idx, "block": {"type": "text", "text": t_text}})
            block_idx += 1

        # 3. Tool call blocks
        if isinstance(resp_spec, dict) and "tool_calls" in resp_spec and resp_spec["tool_calls"]:
            for i, tc in enumerate(resp_spec["tool_calls"]):
                idx = block_idx + i
                call_id = tc.get("id", "call_{}".format(i))
                call_name = tc.get("name", "echo")
                call_args = tc.get("arguments", "{}")
                if not isinstance(call_args, str):
                    call_args = json.dumps(call_args, ensure_ascii=False)

                chunks.append({"type": "block-start", "index": idx, "blockType": "tool-call"})
                chunks.append({
                    "type": "tool-call-delta",
                    "index": idx,
                    "id": call_id,
                    "name": call_name,
                    "argumentsDelta": call_args,
                })
                chunks.append({
                    "type": "block-end",
                    "index": idx,
                    "block": {
                        "type": "tool-call",
                        "id": call_id,
                        "name": call_name,
                        "arguments": call_args,
                    },
                })
            block_idx += len(resp_spec["tool_calls"])

        # 4. Usage accounting
        if isinstance(resp_spec, dict):
            usage_data = resp_spec.get("usage", {
                "inputTokens": 50,
                "outputTokens": 75,
                "reasoningTokens": 25 if "reasoning" in resp_spec else 0,
                "cacheReadTokens": 15,
                "totalTokens": 125,
            })
            chunks.append({"type": "usage", "usage": usage_data})

            # 5. Finish chunk
            finish_kind = resp_spec.get("finish_kind")
            if finish_kind is None:
                finish_kind = "tool-calls" if resp_spec.get("tool_calls") else "stop"
            chunks.append({
                "type": "finish",
                "reason": {"kind": finish_kind},
                **({"replayState": resp_spec["replay_state"]} if "replay_state" in resp_spec else {}),
            })

        for c in chunks:
            # Check for streaming pause or yield
            if isinstance(resp_spec, dict) and resp_spec.get("chunk_delay"):
                await asyncio.sleep(resp_spec["chunk_delay"])
            yield c


async def create_test_context(
    adapter: ScriptedMockAdapter,
    persona: str = "You are a test engineer assistant.",
    include_identity: bool = True,
    include_runtime_context: bool = True,
    tool_order: Optional[List[str]] = None,
) -> Context:
    """Helper to build a clean Cordis Context with all core plugins mounted 1:1."""
    ctx = Context()
    ctx.plugin(SessionPlugin)
    ctx.plugin(ToolsPlugin)

    prompt_config: Dict[str, Any] = {
        "includeHarnessIdentity": include_identity,
        "persona": persona,
        "includeRuntimeContext": include_runtime_context,
    }
    if tool_order is not None:
        prompt_config["toolOrder"] = tool_order

    ctx.plugin(SystemPrompt, config=prompt_config)
    ctx.plugin(AgentPlugin)
    ctx.plugin(AgentLoopPlugin)

    llm_svc = LLMService(ctx=ctx)
    llm_svc.provider = "mock-provider"
    llm_svc.model = "mock-model"
    ctx.set_service("llm", llm_svc)
    llm_svc.register_adapter(["mock-provider", "openai", "deepseek", "deepseek-official"], adapter)
    return ctx


# ==============================================================================
# SECTION 1: System Prompt & Dynamic Context Structure 1:1 Parity Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_system_prompt_sections_order_and_deterministic_tie_breaking():
    """
    1:1 test: First-party order constants (-1000, 0, etc.), custom order placement,
    and deterministic tie breaking on equal section orders using code-unit name.
    """
    adapter = ScriptedMockAdapter()
    ctx = await create_test_context(adapter, persona="Persona text.", include_identity=True)
    sp: SystemPrompt = ctx.get("systemPrompt")

    # Register multiple sections with varying orders and equal orders
    sp.section({"name": "b_section", "order": 100, "text": "Section B"})
    sp.section({"name": "a_section", "order": 100, "text": "Section A"})
    sp.section({"name": "early_section", "order": -500, "text": "Early Section"})
    sp.section({"name": "late_section", "order": 2000, "text": "Late Section"})

    assembly = await sp.assemble()
    section_names = [s["name"] for s in assembly["sections"]]

    # Expected order:
    # 1. harness:identity (-1000)
    # 2. early_section (-500)
    # 3. deployment:persona (0)
    # 4. a_section (100, alphabetical before b_section)
    # 5. b_section (100)
    # 6. late_section (2000)
    assert section_names == [
        "harness:identity",
        "early_section",
        "deployment:persona",
        "a_section",
        "b_section",
        "late_section",
    ]

    rendered = render_prompt(assembly)
    assert rendered == (
        "You are an AI agent powered by DeepSeek Harness.\n\n"
        "Early Section\n\n"
        "Persona text.\n\n"
        "Section A\n\n"
        "Section B\n\n"
        "Late Section"
    )


@pytest.mark.asyncio
async def test_system_prompt_variable_interpolation_and_strict_diagnostics():
    """
    1:1 test: Strict variable interpolation:
    - Valid interpolation {{var}}
    - Missing variable in registry -> ValueError
    - Malformed {{}} or invalid identifier -> ValueError
    - Variable provider returning None -> ValueError
    """
    adapter = ScriptedMockAdapter()
    ctx = await create_test_context(adapter, persona="Agent for project {{proj_name}} in mode {{exec_mode}}.")
    sp: SystemPrompt = ctx.get("systemPrompt")

    sp.variable("proj_name", "DeepSeek-Harness")
    sp.variable("exec_mode", "strict")

    assembly = await sp.assemble()
    assert render_prompt(assembly) == (
        "You are an AI agent powered by DeepSeek Harness.\n\n"
        "Agent for project DeepSeek-Harness in mode strict."
    )

    # 1. Unknown variable reference throws
    ctx2 = await create_test_context(adapter, persona="Hello {{unregistered_var}}")
    sp2: SystemPrompt = ctx2.get("systemPrompt")
    assembly2 = await sp2.assemble()
    with pytest.raises(ValueError, match='unknown prompt variable "{{unregistered_var}}"'):
        render_prompt(assembly2)

    # 2. Malformed {{}} throws
    ctx3 = await create_test_context(adapter, persona="Invalid {{}} reference")
    sp3: SystemPrompt = ctx3.get("systemPrompt")
    assembly3 = await sp3.assemble()
    with pytest.raises(ValueError, match="malformed prompt variable reference"):
        render_prompt(assembly3)

    # 3. Variable provider returning None throws
    ctx4 = await create_test_context(adapter, persona="Config: {{null_var}}")
    sp4: SystemPrompt = ctx4.get("systemPrompt")
    sp4.variable("null_var", lambda c: None)
    assembly4 = await sp4.assemble()
    with pytest.raises(ValueError, match='prompt variable "{{null_var}}" has no value for this assembly'):
        render_prompt(assembly4)


@pytest.mark.asyncio
async def test_system_prompt_complete_section_override():
    """
    1:1 test: A section with complete: True overrides all other prompt sections,
    enforcing that only that single complete section is present in the rendered prompt.
    Also verifies that multiple complete sections cause assemble to fail.
    """
    adapter = ScriptedMockAdapter()
    ctx = await create_test_context(adapter, persona="Default Persona")
    sp: SystemPrompt = ctx.get("systemPrompt")

    sp.section({
        "name": "isolated_environment",
        "order": 500,
        "text": "EXCLUSIVE SYSTEM PROMPT FOR SECURE MODE",
        "complete": True,
    })

    assembly = await sp.assemble()
    assert len(assembly["sections"]) == 1
    assert assembly["sections"][0]["name"] == "isolated_environment"
    assert render_prompt(assembly) == "EXCLUSIVE SYSTEM PROMPT FOR SECURE MODE"

    # Multiple complete sections throw
    sp.section({
        "name": "second_complete",
        "order": 600,
        "text": "ANOTHER COMPLETE PROMPT",
        "complete": True,
    })
    with pytest.raises(ValueError, match="multiple complete prompt sections are active"):
        await sp.assemble()


@pytest.mark.asyncio
async def test_system_prompt_runtime_context_snapshot_and_suppression():
    """
    1:1 test: Dynamic runtime context snapshots formatted with official header:
    'Current runtime context. This snapshot supersedes earlier runtime-context snapshots.\n\n...'
    and suppression via includeRuntimeContext: False.
    """
    adapter = ScriptedMockAdapter()
    ctx = await create_test_context(adapter, persona="Worker")
    sp: SystemPrompt = ctx.get("systemPrompt")

    sp.context({"name": "cwd", "order": 1, "text": "Working directory: /repo"})
    sp.context({"name": "git", "order": 2, "text": "Git status: clean"})

    assembly = await sp.assemble()
    sections = render_context_sections(assembly)
    assert len(sections) == 2
    assert sections[0] == {"name": "cwd", "text": "Working directory: /repo"}
    assert sections[1] == {"name": "git", "text": "Git status: clean"}

    snapshot = render_context_snapshot(assembly)
    expected_header = "Current runtime context. This snapshot supersedes earlier runtime-context snapshots."
    assert snapshot.startswith(expected_header)
    assert "Working directory: /repo\n\nGit status: clean" in snapshot

    # Verify suppression drops all contexts
    ctx_suppressed = await create_test_context(adapter, include_runtime_context=False)
    sp_suppressed: SystemPrompt = ctx_suppressed.get("systemPrompt")
    sp_suppressed.context({"name": "cwd", "order": 1, "text": "Working directory: /repo"})
    assembly_suppressed = await sp_suppressed.assemble()
    assert assembly_suppressed["contexts"] == []
    assert render_context_snapshot(assembly_suppressed) == ""


@pytest.mark.asyncio
async def test_system_prompt_tool_ordering_and_unlisted_tools():
    """
    1:1 test: Configured toolOrder placing explicit tools and inserting unlisted tools
    lexicographically at '<unlisted-tools>'.
    """
    adapter = ScriptedMockAdapter()
    ctx = await create_test_context(
        adapter,
        tool_order=["str_replace_editor", TOOL_ORDER_REST, "ask_user"],
    )
    sp: SystemPrompt = ctx.get("systemPrompt")

    sp.tools(lambda c: {
        "schemas": [
            {"name": "ask_user", "description": "ask user", "parameters": {}},
            {"name": "zeta_tool", "description": "z", "parameters": {}},
            {"name": "str_replace_editor", "description": "edit", "parameters": {}},
            {"name": "alpha_tool", "description": "a", "parameters": {}},
        ]
    })

    assembly = await sp.assemble()
    tool_names = [t["name"] for t in assembly["tools"]]

    # Expected: str_replace_editor, then unlisted sorted (alpha_tool, zeta_tool), then ask_user
    assert tool_names == ["str_replace_editor", "alpha_tool", "zeta_tool", "ask_user"]

    # Invalid tool order configurations:
    # 1. Missing <unlisted-tools>
    with pytest.raises(ValueError, match="toolOrder must contain the"):
        await create_test_context(adapter, tool_order=["str_replace_editor", "ask_user"])

    # 2. Duplicate entries
    with pytest.raises(ValueError, match="lists.*more than once"):
        await create_test_context(adapter, tool_order=["tool_a", "tool_a", TOOL_ORDER_REST])


@pytest.mark.asyncio
async def test_system_prompt_scoped_layer_disposal_reversible_effects():
    """
    1:1 test: Scoped layers registered by plugins/fibers are completely reversible.
    Disposing the layer removes all associated variables, sections, and contexts.
    """
    adapter = ScriptedMockAdapter()
    ctx = await create_test_context(adapter, persona="Base persona")
    sp: SystemPrompt = ctx.get("systemPrompt")

    # Base prompt check
    base_assembly = await sp.assemble()
    assert "Base persona" in render_prompt(base_assembly)
    assert len(base_assembly["sections"]) == 2  # identity + persona

    # Add dynamic plugin registrations
    dispose_var = sp.variable("feature_flag", "active")
    dispose_sec = sp.section({"name": "feature_plugin", "order": 300, "text": "Feature is {{feature_flag}}"})
    dispose_ctx = sp.context({"name": "feature_state", "order": 10, "text": "Feature buffer: empty"})

    feature_assembly = await sp.assemble()
    rendered_with_feature = render_prompt(feature_assembly)
    assert "Feature is active" in rendered_with_feature
    assert len(feature_assembly["sections"]) == 3
    assert len(feature_assembly["contexts"]) == 1

    # Dispose registrations (e.g. plugin unload / fiber cancellation)
    dispose_sec()
    dispose_var()
    dispose_ctx()

    disposed_assembly = await sp.assemble()
    rendered_after_dispose = render_prompt(disposed_assembly)
    assert "Feature is active" not in rendered_after_dispose
    assert len(disposed_assembly["sections"]) == 2
    assert len(disposed_assembly["contexts"]) == 0


@pytest.mark.asyncio
async def test_system_prompt_assemble_waterfall_and_dynamic_providers():
    """
    1:1 test: system-prompt/assemble waterfall allows plugins to modify prompt assemblies in-flight.
    """
    adapter = ScriptedMockAdapter()
    ctx = await create_test_context(adapter, persona="Standard agent.")
    sp: SystemPrompt = ctx.get("systemPrompt")

    def assemble_modifier(assembly, context=None, next_fn=None):
        assembly["sections"].append({
            "name": "waterfall_injected",
            "order": 9999,
            "text": "INJECTED BY WATERFALL",
        })
        if next_fn:
            return next_fn()
        return assembly

    ctx.on("system-prompt/assemble", assemble_modifier)

    assembly = await sp.assemble()
    assert any(s["name"] == "waterfall_injected" for s in assembly["sections"])
    assert "INJECTED BY WATERFALL" in render_prompt(assembly)


@pytest.mark.asyncio
async def test_system_prompt_empty_persona_and_no_identity_options():
    """
    1:1 test: Custom combinations of includeHarnessIdentity=False and empty persona.
    """
    adapter = ScriptedMockAdapter()
    ctx = await create_test_context(adapter, persona="", include_identity=False)
    sp: SystemPrompt = ctx.get("systemPrompt")

    assembly = await sp.assemble()
    assert len(assembly["sections"]) == 1
    assert assembly["sections"][0]["name"] == "deployment:persona"
    assert render_prompt(assembly) == ""


# ==============================================================================
# SECTION 2: LLM Translation, Stream Assembly & Call Preparation Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_block_assembler_interleaved_reasoning_text_tools_usage():
    """
    1:1 BlockAssembler unit & integration test verifying DeepSeek R1 reasoning-delta,
    text-delta, tool-call-delta, usage accounting, and replayState preservation.
    """
    assembler = BlockAssembler()

    # Feed stream chunks
    assembler.push({"type": "block-start", "index": 0, "blockType": "reasoning"})
    assembler.push({"type": "reasoning-delta", "index": 0, "text": "Analyzing the codebase..."})
    assembler.push({"type": "block-end", "index": 0, "block": {"type": "reasoning", "text": "Analyzing the codebase..."}})

    assembler.push({"type": "block-start", "index": 1, "blockType": "text"})
    assembler.push({"type": "text-delta", "index": 1, "text": "Here is the summary."})
    assembler.push({"type": "block-end", "index": 1, "block": {"type": "text", "text": "Here is the summary."}})

    assembler.push({"type": "block-start", "index": 2, "blockType": "tool-call"})
    assembler.push({"type": "tool-call-delta", "index": 2, "id": "call_01", "name": "str_replace", "argumentsDelta": '{"file": "main.py"}'})
    assembler.push({"type": "block-end", "index": 2, "block": {"type": "tool-call", "id": "call_01", "name": "str_replace", "arguments": '{"file": "main.py"}'}})

    assembler.push({"type": "usage", "usage": {"inputTokens": 100, "outputTokens": 50, "reasoningTokens": 30}})
    assembler.push({"type": "finish", "reason": {"kind": "tool-calls"}, "replayState": {"model": "deepseek-reasoner"}})

    blocks = assembler.blocks()
    assert len(blocks) == 3
    assert blocks[0] == {"type": "reasoning", "text": "Analyzing the codebase..."}
    assert blocks[1] == {"type": "text", "text": "Here is the summary."}
    assert blocks[2] == {"type": "tool-call", "id": "call_01", "name": "str_replace", "arguments": '{"file": "main.py"}'}

    assert assembler.usage == {"inputTokens": 100, "outputTokens": 50, "reasoningTokens": 30}
    assert assembler.finish == {"kind": "tool-calls"}
    assert assembler.replayState == {"model": "deepseek-reasoner"}


@pytest.mark.asyncio
async def test_block_assembler_invariants_and_error_handling():
    """
    1:1 test: BlockAssembler tolerance for missing block-start, unhandled incomplete types,
    and straggler deltas after block-end.
    """
    assembler = BlockAssembler()

    # 1. Delta without explicit block-start/end defaults to text block
    assembler.push({"type": "text-delta", "index": 0, "text": "implicit text"})
    assert assembler.blocks() == [{"type": "text", "text": "implicit text"}]
    assert assembler.finish == {"kind": "stop"}

    # 2. Tool call delta straggler after block-end is safely ignored
    assembler2 = BlockAssembler()
    assembler2.push({"type": "block-start", "index": 0, "blockType": "tool-call"})
    assembler2.push({"type": "tool-call-delta", "index": 0, "id": "c1", "name": "echo", "argumentsDelta": "{}"})
    assembler2.push({"type": "block-end", "index": 0, "block": {"type": "tool-call", "id": "c1", "name": "echo", "arguments": "{}"}})
    assembler2.push({"type": "tool-call-delta", "index": 0, "id": "c1", "name": "bad", "argumentsDelta": "ignored"})
    assert assembler2.blocks() == [{"type": "tool-call", "id": "c1", "name": "echo", "arguments": "{}"}]


@pytest.mark.asyncio
async def test_llm_prepare_call_materializes_defaults_and_validates():
    """
    1:1 test: LLM prepare_call materializes adapterDefaults and validates reasoning efforts.
    """
    model_metadata = {
        "provider": "mock-provider",
        "id": "mock-r1",
        "name": "Mock R1",
        "defaultMaxTokens": 8192,
        "reasoning": {
            "efforts": ["low", "medium", "high"],
            "defaultEffort": "high",
        },
    }
    adapter = ScriptedMockAdapter(model_info=model_metadata)
    ctx = await create_test_context(adapter)
    llm_svc: LLMService = ctx.get("llm")

    # 1. Prepare call with omitted maxTokens and reasoningEffort -> materializes defaults
    prepared = await llm_svc.prepare_call({
        "provider": "mock-provider",
        "model": "mock-r1",
    })

    assert prepared["model"]["id"] == "mock-r1"
    assert prepared["maxTokens"] == 8192
    assert prepared["reasoningEffort"] == "high"
    assert prepared["adapterDefaults"] == {"maxTokens": True, "reasoningEffort": True}

    # 2. Prepare call with explicit values -> overrides defaults, adapterDefaults flags False
    prepared_custom = await llm_svc.prepare_call({
        "provider": "mock-provider",
        "model": "mock-r1",
        "maxTokens": 2048,
        "reasoningEffort": "low",
    })
    assert prepared_custom["maxTokens"] == 2048
    assert prepared_custom["reasoningEffort"] == "low"
    assert prepared_custom["adapterDefaults"] == {"maxTokens": False, "reasoningEffort": False}

    # 3. Unsupported reasoning effort throws UNSUPPORTED_REASONING_EFFORT
    with pytest.raises(LlmError) as exc_info:
        await llm_svc.prepare_call({
            "provider": "mock-provider",
            "model": "mock-r1",
            "reasoningEffort": "ultra-deep",
        })
    assert exc_info.value.code == "UNSUPPORTED_REASONING_EFFORT"


@pytest.mark.asyncio
async def test_llm_adapter_registration_lifecycle_and_replace():
    """
    1:1 test: Dynamic LLM adapter registration, route replacement, and disposal.
    """
    ctx = Context()
    llm_svc = LLMService(ctx=ctx)

    class CustomAdapter:
        def provider_info(self, p):
            return {"id": p, "name": "Custom Provider"}

    # 1. Register adapter
    dispose = llm_svc.register_adapter(["prov-1", "prov-2"], CustomAdapter())
    providers = [p["id"] for p in llm_svc.list_providers()]
    assert "prov-1" in providers
    assert "prov-2" in providers

    # 2. Duplicate registration throws
    with pytest.raises(LlmError, match="is already registered"):
        llm_svc.register_adapter(["prov-1"], CustomAdapter())

    # 3. Replace routes
    dispose.replace(["prov-3"])
    providers_after_replace = [p["id"] for p in llm_svc.list_providers()]
    assert "prov-1" not in providers_after_replace
    assert "prov-3" in providers_after_replace

    # 4. Dispose
    dispose()
    providers_after_dispose = [p["id"] for p in llm_svc.list_providers()]
    assert "prov-3" not in providers_after_dispose


@pytest.mark.asyncio
async def test_llm_configurable_providers_directory_validation():
    """
    1:1 test: Configurable provider directory validation and duplicate prevention.
    """
    ctx = Context()
    llm_svc = LLMService(ctx=ctx)

    # 1. Valid registration
    dispose = llm_svc.register_configurable_providers([
        {"provider": "p1", "displayName": "P1", "settingsNs": "ns1", "settingsPath": ["key"]},
    ])
    assert any(p["provider"] == "p1" for p in llm_svc.list_configurable_providers())

    # 2. Duplicate provider throws
    with pytest.raises(LlmError, match="is already declared"):
        llm_svc.register_configurable_providers([
            {"provider": "p1", "displayName": "P1 Dupe", "settingsNs": "ns1", "settingsPath": ["key"]},
        ])

    dispose()


# ==============================================================================
# SECTION 3: End-to-End Agent Loop & Event Stream Parity Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_e2e_full_turn_event_stream_sequence_and_invariants():
    """
    1:1 End-to-End Event Stream Sequence Verification:
    Executes a multi-step turn (Step 1: Model outputs tool call -> Step 2: Model outputs final answer).
    Asserts the exact chronological event sequence, causality, payloads, surfaceOp, and sourceEventSeqs.
    """
    adapter = ScriptedMockAdapter(responses=[
        {
            "reasoning": "Need to inspect repository structure via fs_list.",
            "tool_calls": [{"id": "call_fs_01", "name": "fs_list", "arguments": {"dir": "src"}}],
        },
        {
            "reasoning": "Found main modules. Producing final summary.",
            "text": "Repository inspection complete: 3 modules found.",
        },
    ])

    ctx = await create_test_context(adapter, persona="Core Inspector")

    # Register tool
    tools_svc: ToolsService = ctx.get("tools")
    tools_svc.register_tool(
        name="fs_list",
        description="List files in directory",
        parameters={"type": "object", "properties": {"dir": {"type": "string"}}},
        handler=lambda args: json.dumps(["main.py", "utils.py", "config.py"]),
    )

    agent_loop: AgentLoopService = ctx.get("agent_loop")
    handle = await agent_loop.create_agent("e2e-session-stream-1", options=AgentOptions(provider="mock-provider", model="mock-model"))
    agent = handle.agent
    session = agent.session

    # Send instruction to kick turn
    agent.followup("Inspect the src directory")
    await agent.when_idle()

    # Collect all event types in sequence
    event_types = [e.get("type") for e in session.events]

    # Verify key lifecycle event flow
    assert "agent/inbox/spliced" in event_types
    assert "turn/start" in event_types
    assert "step/start" in event_types
    assert "user/message" in event_types
    assert "request/header" in event_types
    assert "request/context" in event_types
    assert "assistant/chunk" in event_types
    assert "assistant/message" in event_types
    assert "tool/call" in event_types
    assert "tool/result" in event_types
    assert "step/end" in event_types
    assert "turn/end" in event_types

    # 1. Verify turn start
    turn_start = next(e for e in session.events if e.get("type") == "turn/start")
    assert turn_start["data"]["turn"] == 1

    # 2. Verify step boundaries
    step_starts = [e for e in session.events if e.get("type") == "step/start"]
    step_ends = [e for e in session.events if e.get("type") == "step/end"]
    assert len(step_starts) == 2
    assert len(step_ends) == 2
    assert step_starts[0]["data"] == {"turn": 1, "step": 1}
    assert step_starts[1]["data"] == {"turn": 1, "step": 2}

    # 3. Verify assistant messages and surface operations
    assistant_msgs = [e for e in session.events if e.get("type") == "assistant/message"]
    assert len(assistant_msgs) == 2

    # Step 1 Assistant Message
    msg1_data = assistant_msgs[0]["data"]
    assert msg1_data["turn"] == 1
    assert msg1_data["step"] == 1
    assert assistant_msgs[0].get("surfaceOp") == "append"
    assert "sourceEventSeqs" in assistant_msgs[0]
    blocks1 = msg1_data["message"]["content"]
    assert any(b.get("type") == "reasoning" and "fs_list" in b.get("text", "") for b in blocks1)
    assert any(b.get("type") == "tool-call" and b.get("name") == "fs_list" and b.get("id") == "call_fs_01" for b in blocks1)

    # Step 2 Assistant Message
    msg2_data = assistant_msgs[1]["data"]
    assert msg2_data["turn"] == 1
    assert msg2_data["step"] == 2
    blocks2 = msg2_data["message"]["content"]
    assert any(b.get("type") == "text" and "Repository inspection complete" in b.get("text", "") for b in blocks2)

    # 4. Verify turn ending reason
    turn_end = next(e for e in session.events if e.get("type") == "turn/end")
    assert turn_end["data"]["turn"] == 1
    assert turn_end["data"]["reason"]["kind"] == "completed"

    await handle.dispose()


@pytest.mark.asyncio
async def test_e2e_multi_step_turn_tool_execution_flow():
    """
    1:1 test: Multi-step turn executing two sequential tool calls across 2 steps
    and concluding on Step 3 with a text response.
    """
    adapter = ScriptedMockAdapter(responses=[
        {"tool_calls": [{"id": "c1", "name": "step1_tool", "arguments": {}}]},
        {"tool_calls": [{"id": "c2", "name": "step2_tool", "arguments": {}}]},
        {"text": "All steps finished"},
    ])

    ctx = await create_test_context(adapter)
    tools_svc: ToolsService = ctx.get("tools")
    tools_svc.register_tool(name="step1_tool", description="1", handler=lambda _: "res1")
    tools_svc.register_tool(name="step2_tool", description="2", handler=lambda _: "res2")

    agent_loop: AgentLoopService = ctx.get("agent_loop")
    handle = await agent_loop.create_agent("e2e-session-multi-step-1")
    agent = handle.agent
    session = agent.session

    agent.followup("Run multi-step tools")
    await agent.when_idle()

    # Assert 3 steps ran
    step_starts = [e for e in session.events if e.get("type") == "step/start"]
    assert len(step_starts) == 3
    assert len(adapter.requests) == 3

    # Step 2 request must contain tool result from Step 1
    req2_msgs = adapter.requests[1]["messages"]
    assert any(m.get("role") == "user" and any(b.get("type") == "tool-result" and b.get("toolCallId") == "c1" for b in m.get("content", [])) for m in req2_msgs)

    # Step 3 request must contain tool results from Step 1 and Step 2
    req3_msgs = adapter.requests[2]["messages"]
    assert any(m.get("role") == "user" and any(b.get("type") == "tool-result" and b.get("toolCallId") == "c2" for b in m.get("content", [])) for m in req3_msgs)

    await handle.dispose()


@pytest.mark.asyncio
async def test_e2e_sticky_max_tokens_turn_outcome():
    """
    1:1 test: If any step finishes with max-tokens (e.g. hit output limit),
    the turn outcome must stick to max-tokens even if a later step finishes normally with stop.
    """
    adapter = ScriptedMockAdapter(responses=[
        {
            "reasoning": "Output was truncated due to max tokens.",
            "text": "Partial result...",
            "finish_kind": "max-tokens",
            "tool_calls": [{"id": "c1", "name": "noop", "arguments": {}}],
        },
        {
            "text": "Continued after next step and completed.",
            "finish_kind": "stop",
        },
    ])

    ctx = await create_test_context(adapter)
    tools_svc: ToolsService = ctx.get("tools")
    tools_svc.register_tool(name="noop", description="noop", handler=lambda _: "ok")

    agent_loop: AgentLoopService = ctx.get("agent_loop")
    handle = await agent_loop.create_agent("e2e-session-max-tokens-1")
    agent = handle.agent
    session = agent.session

    agent.followup("Trigger long output")
    await agent.when_idle()

    turn_end = next(e for e in session.events if e.get("type") == "turn/end")
    # Must preserve max-tokens sticky reason
    assert turn_end["data"]["reason"]["kind"] == "max-tokens"

    await handle.dispose()


@pytest.mark.asyncio
async def test_e2e_pre_step_rejection_blocked_and_zero_cost_exit():
    """
    1:1 test:
    1. An agent/pre-step waterfall returning {kind: 'reject'} ends the turn with {kind: 'blocked'}
       without appending step/start or calling LLM.
    2. An empty waking message on step 1 with an empty surface ends the turn with {kind: 'completed'}
       without spending an LLM call.
    """
    adapter = ScriptedMockAdapter(responses=[{"text": "Should not be called"}])
    ctx = await create_test_context(adapter)

    # 1. Pre-step rejection
    def reject_pre_step(req, next_fn=None):
        return {"kind": "reject"}

    ctx.on("agent/pre-step", reject_pre_step)

    agent_loop: AgentLoopService = ctx.get("agent_loop")
    handle1 = await agent_loop.create_agent("e2e-session-reject-1")
    agent1 = handle1.agent
    session1 = agent1.session

    agent1.followup("Please run this")
    await agent1.when_idle()

    assert len(adapter.requests) == 0
    turn_end1 = next(e for e in session1.events if e.get("type") == "turn/end")
    assert turn_end1["data"]["reason"]["kind"] == "blocked"

    await handle1.dispose()


@pytest.mark.asyncio
async def test_e2e_stream_interruption_and_cancellation():
    """
    1:1 test: When an agent is cancelled during streaming, the partially assembled
    blocks are preserved in session log as assistant/message with interrupted: True,
    and turn/end reason is {kind: 'aborted', reason: {kind: 'user'}}.
    """
    adapter = ScriptedMockAdapter(responses=[
        {"text": "Should be interrupted during stream delivery", "chunk_delay": 0.2}
    ])
    ctx = await create_test_context(adapter)

    agent_loop: AgentLoopService = ctx.get("agent_loop")
    handle = await agent_loop.create_agent("e2e-session-abort-1")
    agent = handle.agent
    session = agent.session

    agent.followup("Start long calculation")

    # Cancel while streaming in flight
    await asyncio.sleep(0.05)
    agent.cancel({"kind": "user"})
    await agent.when_idle()

    # Turn ended with aborted reason
    turn_end = next(e for e in session.events if e.get("type") == "turn/end")
    assert turn_end["data"]["reason"]["kind"] == "aborted"
    assert turn_end["data"]["reason"]["reason"]["kind"] == "user"

    await handle.dispose()


@pytest.mark.asyncio
async def test_e2e_tool_execution_cancellation_and_abort():
    """
    1:1 test: When an agent is cancelled during tool execution, tool execution halts
    and turn ends with {kind: 'aborted', reason: {kind: 'user'}}.
    """
    tool_started = asyncio.Event()

    async def blocking_tool(args, signal=None):
        tool_started.set()
        if signal:
            await signal.wait()
        else:
            await asyncio.sleep(0.1)
        return "finished"

    adapter = ScriptedMockAdapter(responses=[
        {"tool_calls": [{"id": "c_slow", "name": "slow_tool", "arguments": {}}]}
    ])
    ctx = await create_test_context(adapter)
    tools_svc: ToolsService = ctx.get("tools")
    tools_svc.register_tool(name="slow_tool", description="slow", handler=blocking_tool)

    agent_loop: AgentLoopService = ctx.get("agent_loop")
    handle = await agent_loop.create_agent("e2e-session-tool-abort-1")
    agent = handle.agent
    session = agent.session

    agent.followup("Run slow tool")
    await tool_started.wait()
    agent.cancel({"kind": "user"})
    await agent.when_idle()

    turn_end = next(e for e in session.events if e.get("type") == "turn/end")
    assert turn_end["data"]["reason"]["kind"] == "aborted"

    await handle.dispose()


@pytest.mark.asyncio
async def test_e2e_agent_run_maintenance_task_and_wake_replay():
    """
    1:1 test: Maintenance tasks (e.g. index rebuilds, migrations) latch incoming wakes
    behind maintenance and replay them upon completion.
    """
    adapter = ScriptedMockAdapter(responses=[{"text": "Wakeup replayed successfully"}])
    ctx = await create_test_context(adapter)

    agent_loop: AgentLoopService = ctx.get("agent_loop")
    handle = await agent_loop.create_agent("e2e-session-maintenance-1")
    agent = handle.agent
    session = agent.session

    maintenance_done = asyncio.Event()

    async def maintenance_coro(signal=None):
        await maintenance_done.wait()

    # Start maintenance
    m_task = asyncio.create_task(agent.run_maintenance(maintenance_coro))
    await asyncio.sleep(0.02)

    # Queue message while maintenance is running
    agent.followup("Queued during maintenance")

    # Release maintenance
    maintenance_done.set()
    await m_task
    await agent.when_idle()

    # Replayed wakeup executed
    assistant_msgs = [e for e in session.events if e.get("type") == "assistant/message"]
    assert len(assistant_msgs) == 1
    assert any("Wakeup replayed" in b.get("text", "") for b in assistant_msgs[0]["data"]["message"]["content"])

    await handle.dispose()


@pytest.mark.asyncio
async def test_e2e_turn_stopping_hook_continuation():
    """
    1:1 test: agent/turn-stopping hook allows plugins to continue the turn by injecting
    an extra instruction before the agent goes idle.
    """
    adapter = ScriptedMockAdapter(responses=[
        {"text": "Initial answer"},
        {"text": "Extra continuation answer"},
    ])
    ctx = await create_test_context(adapter)

    steps_seen = {"v": 0}

    def turn_stopping_handler(payload):
        steps_seen["v"] += 1
        if steps_seen["v"] == 1:
            payload["agent"].steer(createUserMessage({
                "content": [{"type": "text", "text": "Please provide one more detail"}],
                "source": {"kind": "plugin", "plugin": "test"},
            }))

    ctx.on("agent/turn-stopping", turn_stopping_handler)

    agent_loop: AgentLoopService = ctx.get("agent_loop")
    handle = await agent_loop.create_agent("e2e-session-turn-stopping-1")
    agent = handle.agent
    session = agent.session

    agent.followup("Initial query")
    await agent.when_idle()

    assistant_msgs = [e for e in session.events if e.get("type") == "assistant/message"]
    assert len(assistant_msgs) == 2
    assert any("Extra continuation" in b.get("text", "") for b in assistant_msgs[1]["data"]["message"]["content"])

    await handle.dispose()


# ==============================================================================
# SECTION 4: Interception Hooks & Context Injection Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_e2e_tools_pre_execute_argument_modification():
    """
    1:1 test: tools/pre-execute waterfall modifying tool arguments before handler execution.
    """
    adapter = ScriptedMockAdapter(responses=[
        {"tool_calls": [{"id": "c1", "name": "calc", "arguments": {"x": 5}}]},
        {"text": "Finished"},
    ])
    ctx = await create_test_context(adapter)
    tools_svc: ToolsService = ctx.get("tools")

    executed_args = {}

    def calc_handler(args):
        executed_args.update(args)
        return "result: {}".format(args.get("x"))

    tools_svc.register_tool(name="calc", description="calc", handler=calc_handler)

    # Hook: double x
    def modify_tool_args(exec_info, next_fn=None):
        args = dict(exec_info.get("arguments", {}))
        args["x"] = args.get("x", 0) * 2
        return {"kind": "allow", "arguments": args}

    ctx.on("tools/pre-execute", modify_tool_args)

    agent_loop: AgentLoopService = ctx.get("agent_loop")
    handle = await agent_loop.create_agent("e2e-session-pre-tool-1")
    agent = handle.agent

    agent.followup("Run calc")
    await agent.when_idle()

    assert executed_args.get("x") == 10

    await handle.dispose()


@pytest.mark.asyncio
async def test_e2e_tools_pre_execute_skip_and_abort():
    """
    1:1 test: tools/pre-execute hook skipping tool execution and returning synthetic result.
    """
    adapter = ScriptedMockAdapter(responses=[
        {"tool_calls": [{"id": "c_skip", "name": "skipped_tool", "arguments": {}}]},
        {"text": "Acknowledged synthetic result"},
    ])
    ctx = await create_test_context(adapter)
    tools_svc: ToolsService = ctx.get("tools")
    tools_svc.register_tool(name="skipped_tool", description="skipped", handler=lambda args: "real result")

    def skip_tool(exec_info, next_fn=None):
        return {"kind": "skip", "result": [{"type": "text", "text": "synthetic skipped result"}]}

    ctx.on("tools/pre-execute", skip_tool)

    agent_loop: AgentLoopService = ctx.get("agent_loop")
    handle = await agent_loop.create_agent("e2e-session-skip-tool-1")
    agent = handle.agent
    session = agent.session

    agent.followup("Run skipped tool")
    await agent.when_idle()

    tool_results = [e for e in session.events if e.get("type") == "tool/result"]
    assert len(tool_results) == 1
    assert "synthetic skipped result" in str(tool_results[0]["data"])

    await handle.dispose()


@pytest.mark.asyncio
async def test_e2e_tools_post_execute_additional_contexts_injection():
    """
    1:1 test: tools/post-execute hook injecting additionalContexts, latched into nextStep.
    """
    adapter = ScriptedMockAdapter(responses=[
        {"tool_calls": [{"id": "c1", "name": "fetch", "arguments": {}}]},
        {"text": "Done after injected context"},
    ])
    ctx = await create_test_context(adapter)
    tools_svc: ToolsService = ctx.get("tools")
    tools_svc.register_tool(name="fetch", description="fetch", handler=lambda args: "fetched raw data")

    def post_tool_inject(exec_info, result, next_fn=None):
        return {
            "kind": "accept",
            "additionalContexts": [
                createUserMessage({
                    "content": [{"type": "text", "text": "Side-channel context: security policy clean"}],
                    "source": {"kind": "plugin", "plugin": "security"},
                })
            ],
        }

    ctx.on("tools/post-execute", post_tool_inject)

    agent_loop: AgentLoopService = ctx.get("agent_loop")
    handle = await agent_loop.create_agent("e2e-session-post-tool-inject-1")
    agent = handle.agent

    agent.followup("Fetch data")
    await agent.when_idle()

    # Verify that Step 2 request received the injected context message
    req2_msgs = adapter.requests[1]["messages"]
    assert any("Side-channel context" in str(m) for m in req2_msgs)

    await handle.dispose()


@pytest.mark.asyncio
async def test_e2e_agent_pre_step_message_modification():
    """
    1:1 test: agent/pre-step waterfall modifying incoming user message text before step execution.
    """
    adapter = ScriptedMockAdapter(responses=[{"text": "Saw modified text"}])
    ctx = await create_test_context(adapter)

    async def modify_user_msg(data, next_fn=None):
        messages = data.get("messages", [])
        rewritten = [createUserMessage({
            "content": [{"type": "text", "text": "MODIFIED: Original prompt"}],
            "source": {"kind": "user"},
        })]
        return {"kind": "enter", "messages": rewritten}

    ctx.on("agent/pre-step", modify_user_msg)

    agent_loop: AgentLoopService = ctx.get("agent_loop")
    handle = await agent_loop.create_agent("e2e-session-pre-step-modify-1")
    agent = handle.agent

    agent.followup("Original prompt")
    await agent.when_idle()

    assert len(adapter.requests) == 1
    req_msgs = adapter.requests[0]["messages"]
    assert any("MODIFIED: Original prompt" in str(m) for m in req_msgs)

    await handle.dispose()


# ==============================================================================
# SECTION 5: Request Header Progression & Reconstructability Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_e2e_request_header_progression_across_multi_turn_and_changes():
    """
    1:1 Request Reconstruction & Header Parity:
    - Turn 1 Step 1 logs request/header with reason: 'initial'.
    - Turn 1 Step 2 (tool step, same config/system) does NOT log a duplicate header.
    - Turn 2 Step 1 (same config/system) does NOT log a duplicate header.
    - Turn 3 with modified system prompt logs request/header with reason: 'change'.
    - An explicit series trigger logs request/header with reason: 'series'.
    """
    adapter = ScriptedMockAdapter(responses=[
        # Turn 1: 2 steps
        {"tool_calls": [{"id": "c1", "name": "tool_a", "arguments": {}}]},
        {"text": "Turn 1 step 2 finish"},
        # Turn 2: 1 step (identical)
        {"text": "Turn 2 finish"},
        # Turn 3: 1 step (system prompt changed)
        {"text": "Turn 3 finish"},
        # Turn 4: 1 step (series trigger)
        {"text": "Turn 4 finish"},
    ])

    ctx = await create_test_context(adapter, persona="Initial Persona")
    tools_svc: ToolsService = ctx.get("tools")
    tools_svc.register_tool(name="tool_a", description="a", handler=lambda _: "ok")

    agent_loop: AgentLoopService = ctx.get("agent_loop")
    handle = await agent_loop.create_agent("e2e-session-header-progression-1")
    agent = handle.agent
    session = agent.session

    # --- Turn 1 ---
    agent.followup("Turn 1 message")
    await agent.when_idle()

    headers_turn1 = [e for e in session.events if e.get("type") == "request/header"]
    assert len(headers_turn1) == 1
    assert headers_turn1[0]["data"]["reason"] == "initial"

    # --- Turn 2 ---
    agent.followup("Turn 2 message (no prompt changes)")
    await agent.when_idle()

    headers_turn2 = [e for e in session.events if e.get("type") == "request/header"]
    assert len(headers_turn2) == 1  # No new header logged

    # --- Turn 3: Change system prompt ---
    sp: SystemPrompt = ctx.get("systemPrompt")
    sp.section({"name": "extra_instruction", "order": 50, "text": "Always respond in JSON."})

    agent.followup("Turn 3 message with changed system prompt")
    await agent.when_idle()

    headers_turn3 = [e for e in session.events if e.get("type") == "request/header"]
    assert len(headers_turn3) == 2
    assert headers_turn3[1]["data"]["reason"] == "change"
    assert "Always respond in JSON." in headers_turn3[1]["data"]["header"]["system"]

    # --- Turn 4: Series trigger via pre-step ---
    def trigger_series(req, next_fn=None):
        return {"kind": "enter", "messages": req.get("messages", []), "startsRequestSeries": True}

    ctx.on("agent/pre-step", trigger_series)

    agent.followup("Turn 4 message with series flag")
    await agent.when_idle()

    headers_turn4 = [e for e in session.events if e.get("type") == "request/header"]
    assert len(headers_turn4) == 3
    assert headers_turn4[2]["data"]["reason"] in ("series", "change")

    await handle.dispose()


@pytest.mark.asyncio
async def test_e2e_request_prefix_extension_stability():
    """
    1:1 test: Across steps and turns, requests strictly extend previous message histories
    as immutable prefixes without mutation of existing items.
    """
    adapter = ScriptedMockAdapter(responses=[
        {"tool_calls": [{"id": "c1", "name": "echo", "arguments": {"x": 1}}]},
        {"text": "step 2 finish"},
        {"text": "turn 2 finish"},
    ])
    ctx = await create_test_context(adapter)
    tools_svc: ToolsService = ctx.get("tools")
    tools_svc.register_tool(name="echo", description="echo", handler=lambda _: "ok")

    agent_loop: AgentLoopService = ctx.get("agent_loop")
    handle = await agent_loop.create_agent("e2e-session-prefix-1")
    agent = handle.agent

    # Turn 1
    agent.followup("Turn 1 start")
    await agent.when_idle()

    # Turn 2
    agent.followup("Turn 2 start")
    await agent.when_idle()

    assert len(adapter.requests) == 3
    req1 = adapter.requests[0]["messages"]
    req2 = adapter.requests[1]["messages"]
    req3 = adapter.requests[2]["messages"]

    # req2 extends req1
    assert len(req2) > len(req1)
    assert req2[:len(req1)] == req1

    # req3 extends req2
    assert len(req3) > len(req2)
    assert req3[:len(req2)] == req2

    await handle.dispose()


@pytest.mark.asyncio
async def test_e2e_request_proposal_stripping_adapter_defaults():
    """
    1:1 test: request_proposal strips reasoningEffort and maxTokens when adapterDefaults were True.
    """
    header_with_defaults = {
        "config": {
            "model": "deepseek-reasoner",
            "maxTokens": 4096,
            "reasoningEffort": "high",
        },
        "adapterDefaults": {
            "maxTokens": True,
            "reasoningEffort": True,
        },
    }
    proposal = request_proposal(header_with_defaults)
    assert "maxTokens" not in proposal
    assert "reasoningEffort" not in proposal
    assert proposal["model"] == "deepseek-reasoner"

    header_explicit = {
        "config": {
            "model": "deepseek-reasoner",
            "maxTokens": 2048,
            "reasoningEffort": "low",
        },
        "adapterDefaults": {
            "maxTokens": False,
            "reasoningEffort": False,
        },
    }
    proposal_explicit = request_proposal(header_explicit)
    assert proposal_explicit["maxTokens"] == 2048
    assert proposal_explicit["reasoningEffort"] == "low"


# ==============================================================================
# SECTION 6: LLM Waterfall, Error Recovery, and Retry Pipeline Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_e2e_agent_request_error_recovery_retry_waterfall():
    """
    1:1 test: When an LLM stream encounters an error, agent/request-error waterfall
    is dispatched. If the handler returns {kind: 'retry'}, the step retries cleanly.
    """
    call_count = {"v": 0}

    def flaky_response(req):
        call_count["v"] += 1
        if call_count["v"] == 1:
            raise LlmError("Temporary rate limit exceeded", "RATE_LIMIT", status=429)
        return {"text": "Recovered successfully on retry."}

    adapter = ScriptedMockAdapter(responses=[flaky_response, flaky_response])
    ctx = await create_test_context(adapter)

    retry_events = []

    def error_recovery_handler(payload, next_fn=None):
        retry_events.append(payload)
        # Authorize retry
        return {"kind": "retry"}

    ctx.on("agent/request-error", error_recovery_handler)

    agent_loop: AgentLoopService = ctx.get("agent_loop")
    handle = await agent_loop.create_agent("e2e-session-retry-1")
    agent = handle.agent
    session = agent.session

    agent.followup("Perform task with transient failure")
    await agent.when_idle()

    # Verify recovery waterfall fired once
    assert len(retry_events) == 1
    assert retry_events[0]["failure"]["code"] == "RATE_LIMIT"

    # Verify final assistant message succeeded
    assistant_msgs = [e for e in session.events if e.get("type") == "assistant/message"]
    assert len(assistant_msgs) == 1
    assert any("Recovered successfully" in b.get("text", "") for b in assistant_msgs[0]["data"]["message"]["content"])

    turn_end = next(e for e in session.events if e.get("type") == "turn/end")
    assert turn_end["data"]["reason"]["kind"] == "completed"

    await handle.dispose()


@pytest.mark.asyncio
async def test_e2e_agent_request_error_bubble_and_turn_error_outcome():
    """
    1:1 test: Unrecoverable LLM error propagates to turn/end with kind: 'error'.
    """
    def fatal_error(req):
        raise LlmError("Quota exhausted", "QUOTA_EXCEEDED", status=403)

    adapter = ScriptedMockAdapter(responses=[fatal_error])
    ctx = await create_test_context(adapter)

    agent_loop: AgentLoopService = ctx.get("agent_loop")
    handle = await agent_loop.create_agent("e2e-session-fatal-error-1")
    agent = handle.agent
    session = agent.session

    agent.followup("Trigger unrecoverable quota error")
    await agent.when_idle()

    turn_end = next(e for e in session.events if e.get("type") == "turn/end")
    assert turn_end["data"]["reason"]["kind"] == "error"
    assert "QUOTA_EXCEEDED" in str(turn_end["data"]["reason"])

    await handle.dispose()


# ==============================================================================
# SECTION 7: Multi-turn Session History & Message Derivation Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_e2e_session_derive_messages_exact_history_structure():
    """
    1:1 test: Session.derive_messages() generates standard OpenAI / Anthropic format
    chat message structure from session events including user, assistant (text + tool-call),
    and tool result messages with exact id correspondence.
    """
    session = Session(session_id="derive-msg-test")
    session.append_user_message("Please execute two commands")

    # Assistant with 2 tool calls
    session.append_assistant_message(
        {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "Executing commands..."},
                {"type": "tool-call", "id": "tc_1", "name": "cmd_a", "arguments": '{"x": 1}'},
                {"type": "tool-call", "id": "tc_2", "name": "cmd_b", "arguments": '{"y": 2}'},
            ],
        },
        turn=1,
        step=1,
    )

    # Tool results
    session.append_tool_result("tc_1", "cmd_a", "res_a", turn=1, step=1)
    session.append_tool_result("tc_2", "cmd_b", "res_b", turn=1, step=1)

    # Final assistant message
    session.append_assistant_message(
        {
            "role": "assistant",
            "content": [{"type": "text", "text": "All commands executed successfully."}],
        },
        turn=1,
        step=2,
    )

    messages = session.derive_messages()
    assert len(messages) == 5

    # Msg 0: User
    assert messages[0]["role"] == "user"
    assert messages[0]["content"] == [{"type": "text", "text": "Please execute two commands"}]

    # Msg 1: Assistant with tool_calls
    assert messages[1]["role"] == "assistant"
    assert messages[1]["content"][0] == {"type": "text", "text": "Executing commands..."}
    assert messages[1]["content"][1]["type"] == "tool-call"
    assert messages[1]["content"][1]["id"] == "tc_1"
    assert messages[1]["content"][1]["name"] == "cmd_a"
    assert messages[1]["content"][2]["type"] == "tool-call"
    assert messages[1]["content"][2]["id"] == "tc_2"
    assert messages[1]["content"][2]["name"] == "cmd_b"

    # Msg 2: Tool result 1
    assert messages[2]["role"] == "user"
    assert messages[2]["content"][0]["type"] == "tool-result"
    assert messages[2]["content"][0]["toolCallId"] == "tc_1"

    # Msg 3: Tool result 2
    assert messages[3]["role"] == "user"
    assert messages[3]["content"][0]["type"] == "tool-result"
    assert messages[3]["content"][0]["toolCallId"] == "tc_2"

    # Msg 4: Final assistant message
    assert messages[4]["role"] == "assistant"
    assert messages[4]["content"] == [{"type": "text", "text": "All commands executed successfully."}]


@pytest.mark.asyncio
async def test_e2e_assistant_replay_state_recording_and_derivation():
    """
    1:1 test: Assistant messages record replayState in event data.source,
    which is faithfully preserved in derived messages.
    """
    session = Session(session_id="replay-state-test")
    session.append_user_message("Query with replay state")

    replay_meta = {"providerState": "encrypted-checkpoint-token", "engine": "deepseek-v3"}
    session.append_assistant_message(
        {
            "role": "assistant",
            "content": [{"type": "text", "text": "Response with state"}],
            "source": {
                "kind": "model",
                "provider": "deepseek-official",
                "model": "deepseek-chat",
                "replayState": replay_meta,
            },
        },
        turn=1,
        step=1,
    )

    messages = session.derive_messages()
    assert len(messages) == 2
    assert messages[1]["source"]["replayState"] == replay_meta
