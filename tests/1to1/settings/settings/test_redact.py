"""
1:1 test parity suite for @deepseek-ai/dsh-settings/redact.ts.
Matching reference packages/settings/settings/tests/redact.spec.ts.

Language adaptation: JavaScript `undefined` reads as the port's undefined
sentinel (`dsh.cordis.utils._UNDEFINED`), which is how an absent object
property stays distinct from a stored JSON `null`.
"""

from typing import Any, Dict

import pytest

from dsh.cordis.context import Context
from dsh.cordis.schema import Schema
from dsh.cordis.utils import _UNDEFINED
from dsh.settings.provider import settings_namespace
from dsh.settings.redact import redact_secrets

from .memory import MemorySettings

ProfileSchema = Schema.object({
    "apiKey": Schema.string().role("secret"),
    "apiKeyEnv": Schema.string().role("credential-ref"),
    "baseURL": Schema.string(),
})

AdapterSchema = Schema.object({
    "apiKey": Schema.string().role("secret"),
    "providers": Schema.dict(ProfileSchema),
    "fallbacks": Schema.array(ProfileSchema),
    "nested": Schema.object({
        "token": Schema.string().role("secret"),
    }),
})


class TestRedactSecrets:
    def test_strips_secrets_from_object_dict_and_array_containers_and_records_each_position(self):
        redacted = redact_secrets(AdapterSchema, {
            "apiKey": "top-secret",
            "providers": {
                "openai": {"apiKey": "sk-live", "apiKeyEnv": "OPENAI_API_KEY", "baseURL": "https://x"},
                "anthropic": {"apiKeyEnv": "ANTHROPIC_API_KEY"},
            },
            "fallbacks": [{"apiKey": "fb", "baseURL": "https://y"}],
            "nested": {},
        })
        assert redacted.value == {
            "providers": {
                "openai": {"apiKeyEnv": "OPENAI_API_KEY", "baseURL": "https://x"},
                "anthropic": {"apiKeyEnv": "ANTHROPIC_API_KEY"},
            },
            "fallbacks": [{"baseURL": "https://y"}],
            "nested": {},
        }
        assert [secret.to_dict() for secret in redacted.secrets] == [
            {"path": ["apiKey"], "set": True},
            {"path": ["providers", "openai", "apiKey"], "set": True},
            {"path": ["providers", "anthropic", "apiKey"], "set": False},
            {"path": ["fallbacks", "0", "apiKey"], "set": True},
            {"path": ["nested", "token"], "set": False},
        ]

    def test_enumerates_unset_object_property_slots_without_inventing_containers(self):
        redacted = redact_secrets(AdapterSchema, _UNDEFINED)
        assert redacted.value is _UNDEFINED
        assert [secret.to_dict() for secret in redacted.secrets] == [
            {"path": ["apiKey"], "set": False},
            {"path": ["nested", "token"], "set": False},
        ]

    def test_never_mutates_the_input_and_preserves_keys_outside_the_schema(self):
        input_value: Dict[str, Any] = {"apiKey": "frozen", "extra": {"keep": True}}
        redacted = redact_secrets(AdapterSchema, input_value)
        assert input_value["apiKey"] == "frozen"
        assert redacted.value == {"extra": {"keep": True}}
        assert redacted.value["extra"] == {"keep": True}

    def test_passes_malformed_container_values_through_untouched(self):
        redacted = redact_secrets(AdapterSchema, {
            "providers": "not-a-dict",
            "fallbacks": "not-an-array",
        })
        assert redacted.value == {"providers": "not-a-dict", "fallbacks": "not-an-array"}
        assert [secret.to_dict() for secret in redacted.secrets] == [
            {"path": ["apiKey"], "set": False},
            {"path": ["nested", "token"], "set": False},
        ]

    def test_treats_a_secret_role_container_as_one_opaque_secret_leaf(self):
        weird = Schema.object({"blob": Schema.object({"inner": Schema.string()}).role("secret")})
        redacted = redact_secrets(weird, {"blob": {"inner": "x"}})
        assert redacted.value == {}
        assert [secret.to_dict() for secret in redacted.secrets] == [{"path": ["blob"], "set": True}]

    def test_drops_a_dict_entry_whose_entire_value_is_the_secret(self):
        tokens = Schema.object({"tokens": Schema.dict(Schema.string().role("secret"))})
        redacted = redact_secrets(tokens, {"tokens": {"a": "x", "b": "y"}})
        assert redacted.value == {"tokens": {}}
        assert [secret.to_dict() for secret in redacted.secrets] == [
            {"path": ["tokens", "a"], "set": True},
            {"path": ["tokens", "b"], "set": True},
        ]

    def test_tolerates_structural_nodes_missing_their_relation_maps(self):
        # The port's plain-mapping schema form carries the same structural keys
        # (`type`, `meta`, `dict`, `inner`) a live schemastery node exposes.
        assert redact_secrets({"type": "dict"}, {"k": "v"}).value == {"k": "v"}
        assert redact_secrets({"type": "dict"}, {"k": "v"}).secrets == []
        assert redact_secrets({"type": "object"}, {"k": "v"}).value == {"k": "v"}
        assert redact_secrets({"type": "object"}, {"k": "v"}).secrets == []
        assert redact_secrets({"type": "array"}, ["v"]).value == ["v"]
        assert redact_secrets({"type": "array"}, ["v"]).secrets == []


class TestDescribeLayersAndRedaction:
    NS = settings_namespace("adapter")

    @staticmethod
    async def boot(doc: Any = _UNDEFINED) -> Context:
        ctx = Context()
        await ctx.plugin(MemorySettings, None if doc is _UNDEFINED else {"doc": doc})
        return ctx

    @pytest.mark.asyncio
    async def test_exposes_detached_base_and_user_layers_beside_the_resolved_value(self):
        ctx = await self.boot({"adapter": {"baseURL": "https://user"}})
        base = {"apiKey": "entry-key", "baseURL": "https://base"}
        ctx.get("settings").register(self.NS, ProfileSchema, {"base": base})
        descriptor = ctx.get("settings").describe()[0]
        assert descriptor["base"] == base
        assert descriptor["base"] is not base
        assert descriptor["user"] == {"baseURL": "https://user"}
        assert descriptor["value"] == {"apiKey": "entry-key", "baseURL": "https://user"}
        descriptor["user"]["baseURL"] = "mutated"
        assert ctx.get("settings").describe()[0]["user"] == {"baseURL": "https://user"}
        assert descriptor.get("secrets") is None

    @pytest.mark.asyncio
    async def test_omits_the_layers_when_neither_a_base_nor_a_user_section_exists(self):
        ctx = await self.boot()
        ctx.get("settings").register(self.NS, ProfileSchema)
        descriptor = ctx.get("settings").describe()[0]
        assert "base" not in descriptor
        assert "user" not in descriptor

    @pytest.mark.asyncio
    async def test_describes_a_section_that_became_malformed_after_registration_as_having_no_user_layer(self):
        ctx = await self.boot({"adapter": {"baseURL": "https://user"}})
        provider = ctx.get("settings")
        ctx.get("settings").register(self.NS, ProfileSchema, {"base": {"baseURL": "https://base"}})
        provider.push_external({"adapter": 5})
        descriptor = provider.describe()[0]
        assert "user" not in descriptor
        # The malformed publish kept the last good resolved value.
        assert descriptor["value"] == {"baseURL": "https://user"}

    @pytest.mark.asyncio
    async def test_redacts_a_descriptor_that_has_neither_base_nor_user_layer(self):
        ctx = await self.boot()
        ctx.get("settings").register(self.NS, ProfileSchema)
        descriptor = ctx.get("settings").describe({"redactSecrets": True})[0]
        assert "base" not in descriptor
        assert "user" not in descriptor
        assert descriptor["secrets"] == [{"path": ["apiKey"], "set": False}]

    @pytest.mark.asyncio
    async def test_redacts_every_layer_and_enumerates_secret_slots_under_redactsecrets(self):
        ctx = await self.boot({"adapter": {"apiKey": "user-key", "baseURL": "https://user"}})
        ctx.get("settings").register(self.NS, ProfileSchema, {"base": {"apiKey": "entry-key"}})
        descriptor = ctx.get("settings").describe({"redactSecrets": True})[0]
        assert descriptor["value"] == {"baseURL": "https://user"}
        assert descriptor["base"] == {}
        assert descriptor["user"] == {"baseURL": "https://user"}
        assert descriptor["secrets"] == [{"path": ["apiKey"], "set": True}]
        verbatim = ctx.get("settings").describe()[0]
        assert verbatim["value"] == {"apiKey": "user-key", "baseURL": "https://user"}
