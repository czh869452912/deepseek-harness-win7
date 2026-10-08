"""Explicit test-only LLM provider loaded before canonical activation checks."""
from test_e2e_core_spine_strict_parity import StrictMockLlmAdapter


def plugin(ctx, config):
    ctx.provide('llm', StrictMockLlmAdapter((config or {}).get('responses', [])))
