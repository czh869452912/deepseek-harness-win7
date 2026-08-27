"""
Unit tests for dsh.credentials family achieving 1:1 parity with TS original packages.
"""

import json
import os
import tempfile
import pytest
import yaml

from dsh.cordis.context import Context
from dsh.credentials import (
    ApiKeyRecord,
    AuthorizationDeclinedError,
    AuthorizationError,
    AuthorizationFlow,
    AuthorizationService,
    CredentialInfo,
    CredentialProvider,
    CredentialRecordEntry,
    CredentialRecordInfo,
    CredentialsLocalPlugin,
    CredentialsService,
    GrantRecord,
    LocalCredentialProvider,
    ResolvedCredential,
    apply_authorization_invariant,
    apply_credentials_invariant,
    assert_owner_only,
    credentialKey,
    credentialKeyId,
    credentialKeyScope,
    credentialRef,
    credential_key,
    credential_key_id,
    credential_key_scope,
    credential_ref,
    ensure_cold_start,
    isCredentialKeySegment,
    isCredentialRefName,
    is_credential_key_segment,
    is_credential_ref_name,
    parseCredentialKey,
    parse_credential_key,
    parse_credentials_document,
)


def test_credential_brand_grammar_helpers():
    # POSIX ref validation
    assert is_credential_ref_name("DEEPSEEK_API_KEY") is True
    assert is_credential_ref_name("OPENAI_API_KEY_2") is True
    assert is_credential_ref_name("invalid-name") is False
    assert is_credential_ref_name("123NAME") is False

    assert credential_ref("DEEPSEEK_API_KEY") == "DEEPSEEK_API_KEY"
    assert credentialRef("OPENAI_API_KEY") == "OPENAI_API_KEY"
    with pytest.raises(TypeError):
        credential_ref("invalid-name")

    # Key segment validation
    assert is_credential_key_segment("llm-pi-ai") is True
    assert is_credential_key_segment("openai-codex") is True
    assert is_credential_key_segment("Invalid_Segment") is False

    # Key building and parsing
    key = credential_key("llm-pi-ai", "openai-codex")
    assert key == "llm-pi-ai/openai-codex"
    assert parse_credential_key(key) == "llm-pi-ai/openai-codex"
    assert credential_key_scope(key) == "llm-pi-ai"
    assert credential_key_id(key) == "openai-codex"

    # CamelCase aliases
    assert credentialKey("llm-pi-ai", "openai-codex") == key
    assert parseCredentialKey(key) == key
    assert credentialKeyScope(key) == "llm-pi-ai"
    assert credentialKeyId(key) == "openai-codex"

    with pytest.raises(TypeError):
        credential_key("InvalidScope", "valid-id")

    with pytest.raises(TypeError):
        parse_credential_key("invalidkeyformat")


def test_credentials_document_parsing_and_migration():
    with tempfile.TemporaryDirectory() as tmpdir:
        doc_file = os.path.join(tmpdir, ".credentials.yaml")

        # Flat layout error message check when version is missing
        flat_yaml = "DEEPSEEK_API_KEY: sk-test-123\n"
        with pytest.raises(ValueError) as exc:
            parse_credentials_document(flat_yaml, doc_file)
        assert "uses the pre-release flat layout" in str(exc.value)

        # Version 1 parsing
        v1_yaml = """
version: 1
refs:
  DEEPSEEK_API_KEY: sk-test-v1
records:
  llm-pi-ai/route-1:
    kind: api-key
    key: sk-rec-1
"""
        parsed = parse_credentials_document(v1_yaml, doc_file)
        assert parsed["refs"]["DEEPSEEK_API_KEY"] == "sk-test-v1"
        assert parsed["records"]["llm-pi-ai/route-1"]["key"] == "sk-rec-1"

        # Invalid version
        v2_yaml = "version: 2\nrefs: {}\n"
        with pytest.raises(ValueError) as excinfo:
            parse_credentials_document(v2_yaml, doc_file)
        assert "declares version 2" in str(excinfo.value)

        # Unknown top level key
        unknown_yaml = "version: 1\nunknown_key: foo\n"
        with pytest.raises(ValueError) as excinfo:
            parse_credentials_document(unknown_yaml, doc_file)
        assert "unknown top-level key" in str(excinfo.value)


def test_local_credential_provider_resolved_credential(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    with tempfile.TemporaryDirectory() as tmpdir:
        creds_file = os.path.join(tmpdir, ".credentials.yaml")
        ctx = Context()
        creds = LocalCredentialProvider(ctx=ctx, config={"path": creds_file})

        # Unset reference resolve returns None
        assert creds.resolve("DEEPSEEK_API_KEY") is None
        info = creds.describe("DEEPSEEK_API_KEY")
        assert info["configured"] is False
        assert info["writable"] is True

        # Set reference
        creds.set("DEEPSEEK_API_KEY", "sk-file-123")
        res = creds.resolve("DEEPSEEK_API_KEY")
        assert res is not None
        assert res.value == "sk-file-123"
        assert res.source == "file"
        assert res["value"] == "sk-file-123"
        assert res["source"] == "file"
        # Test backward-compatible string equality
        assert res == "sk-file-123"

        info = creds.describe("DEEPSEEK_API_KEY")
        assert info.configured is True
        assert info.source == "file"
        assert info.writable is True

        # Inherited env shadowing check
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-env-override")
        res_env = creds.resolve("DEEPSEEK_API_KEY")
        assert res_env.value == "sk-env-override"
        assert res_env.source == "env"

        info_env = creds.describe("DEEPSEEK_API_KEY")
        assert info_env.configured is True
        assert info_env.source == "env"
        assert info_env.writable is False

        # Attempt to set shadowed credential raises error
        with pytest.raises(ValueError) as exc:
            creds.set("DEEPSEEK_API_KEY", "sk-new-val")
        assert "supplied read-only by the launching environment" in str(exc.value)

        # Attempt to unset shadowed credential raises error
        with pytest.raises(ValueError) as exc:
            creds.unset("DEEPSEEK_API_KEY")
        assert "supplied read-only by the launching environment" in str(exc.value)


def test_record_management_parity():
    with tempfile.TemporaryDirectory() as tmpdir:
        creds_file = os.path.join(tmpdir, ".credentials.yaml")
        ctx = Context()
        events = []
        ctx.on("credentials/record-updated", lambda key: events.append(key))

        creds = CredentialsService(ctx=ctx, credentials_file=creds_file)
        key = "llm-pi-ai/test-route"

        assert creds.read_record(key) is None
        assert creds.describe_record(key)["configured"] is False

        # Modify record (api-key kind)
        def mutate_api_key(cur):
            return {"kind": "api-key", "key": "sk-secret-key-1", "env": {"AWS_PROFILE": "dev"}}

        rec = creds.modify_record(key, mutate_api_key)
        assert rec["kind"] == "api-key"
        assert rec["key"] == "sk-secret-key-1"
        assert rec["env"]["AWS_PROFILE"] == "dev"
        assert key in events

        desc = creds.describe_record(key)
        assert desc.configured is True
        assert desc.kind == "api-key"

        entries = creds.list_records()
        assert len(entries) == 1
        assert entries[0]["key"] == key
        assert entries[0]["kind"] == "api-key"

        # Modify record (grant kind)
        grant_key = "llm-pi-ai/oauth-grant"

        def mutate_grant(cur):
            return {"kind": "grant", "payload": {"token": "access_token_123", "expires": 3600}}

        rec_grant = creds.modify_record(grant_key, mutate_grant)
        assert rec_grant["kind"] == "grant"
        assert rec_grant["payload"]["token"] == "access_token_123"

        # Non-JSON payload rejection
        with pytest.raises(TypeError):
            creds.modify_record(grant_key, lambda cur: {"kind": "grant", "payload": lambda: None})

        # Delete record
        creds.delete_record(key)
        assert creds.read_record(key) is None
        assert creds.describe_record(key)["configured"] is False


def test_authorization_service_parity():
    ctx = Context()
    creds_service = CredentialsService(ctx=ctx)

    auth = AuthorizationService(ctx=ctx)
    ctx.set_service("authorization", auth)

    key = "llm-pi-ai/openai-codex"

    def mock_flow_run(session):
        session.notify({"message": "Starting authorization"})
        # Commit record through credentials
        creds_service.modify_record(key, lambda cur: {"kind": "api-key", "key": "sk-auth-key"})

    flow = AuthorizationFlow(
        key=key,
        label="ChatGPT (Codex)",
        methods=[{"id": "oauth", "label": "Sign in with ChatGPT"}],
        run_fn=mock_flow_run,
    )

    # 1. Register flow
    dispose = auth.register_flow(flow)

    assert len(auth.list()) == 1
    assert auth.describe(key)["label"] == "ChatGPT (Codex)"

    # Duplicate flow error
    with pytest.raises(AuthorizationError) as exc:
        auth.register_flow(flow)
    assert exc.value.code == "DUPLICATE_FLOW"

    # 2. Begin attempt
    notices = []

    class MockInteraction:
        def notify(self, notice):
            notices.append(notice)

        def prompt(self, prompt_data):
            return "response"

    settled_events = []
    ctx.on("authorization/settled", lambda k, status: settled_events.append((k, status)))

    outcome = auth.begin({
        "key": key,
        "method": "oauth",
        "interaction": MockInteraction(),
    })

    assert outcome["status"] == "authorized"
    assert len(notices) == 1
    assert notices[0]["message"] == "Starting authorization"
    assert creds_service.read_record(key)["key"] == "sk-auth-key"
    assert (key, "authorized") in settled_events

    # 3. Dispose flow
    dispose()
    assert len(auth.list()) == 0


def test_authorization_uncommitted_flow_error():
    ctx = Context()
    creds_service = CredentialsService(ctx=ctx)

    auth = AuthorizationService(ctx=ctx)
    ctx.set_service("authorization", auth)

    key = "llm-pi-ai/no-commit-route"

    def no_commit_run(session):
        # Resolves without committing record
        pass

    auth.register_flow(AuthorizationFlow(
        key=key,
        label="No Commit Flow",
        methods=[{"id": "dummy", "label": "Dummy"}],
        run_fn=no_commit_run,
    ))

    class MockInteraction:
        def notify(self, notice):
            pass

        def prompt(self, prompt_data):
            return ""

    with pytest.raises(AuthorizationError) as exc:
        auth.begin({"key": key, "interaction": MockInteraction()})
    assert exc.value.code == "NOT_COMMITTED"


def test_authorization_declined_error():
    ctx = Context()
    creds_service = CredentialsService(ctx=ctx)

    auth = AuthorizationService(ctx=ctx)
    ctx.set_service("authorization", auth)

    key = "llm-pi-ai/declined-route"

    def prompt_declined_run(session):
        session.prompt({"kind": "text", "message": "Enter code"})

    auth.register_flow(AuthorizationFlow(
        key=key,
        label="Declined Flow",
        methods=[{"id": "dummy", "label": "Dummy"}],
        run_fn=prompt_declined_run,
    ))

    class DecliningInteraction:
        def notify(self, notice):
            pass

        def prompt(self, prompt_data):
            raise AuthorizationDeclinedError()

    outcome = auth.begin({"key": key, "interaction": DecliningInteraction()})
    assert outcome["status"] == "cancelled"


def test_credentials_and_authorization_invariants():
    ctx = Context()
    invariants_log = []

    class MockInvariantsService:
        def register(self, pkg, install_fn):
            install_fn(ctx, lambda msg: invariants_log.append((pkg, msg)))
            return lambda: None

    ctx.set_service("invariants", MockInvariantsService())

    apply_credentials_invariant(ctx)
    apply_authorization_invariant(ctx)

    # Fire reference updated when no credentials service is registered
    ctx.emit("credentials/reference-updated", "DEEPSEEK_API_KEY")
    assert len(invariants_log) == 1
    assert "emitted without a live credentials service" in invariants_log[0][1]

    # Fire authorization settled when no authorization service is registered
    ctx.emit("authorization/settled", "llm-pi-ai/route-1", "authorized")
    assert len(invariants_log) == 2
    assert "emitted without a live authorization service" in invariants_log[1][1]
