"""
Unit tests for session snapshot identity redaction.
Ported 1:1 from reference packages/test-support/session-snapshot/tests/identity.spec.ts.
Compatible with Python 3.8.10 and Windows 7 SP1.
"""

import json
import re
import pytest

from .session_snapshot.identity import redactSessionSnapshotIds

parentId = "11111111-1111-4111-8111-111111111111"
childId = "22222222-2222-4222-8222-222222222222"
messageId = "33333333-3333-4333-8333-333333333333"
approvalId = "44444444-4444-4444-8444-444444444444"
runId = "55555555-5555-4555-8555-555555555555"
otherId = "66666666-6666-4666-8666-666666666666"
proseUuid = "77777777-7777-4777-8777-777777777777"


def _dumps(obj):
    return json.dumps(obj, separators=(",", ":"))


class TestSessionSnapshotIdentityRedaction:
    def test_preserves_typed_relationships_across_parent_and_child_logs(self):
        parent = "\n".join([
            _dumps({"type": "session", "id": parentId, "createdAt": 1, "cwd": "/tmp/work"}),
            _dumps({
                "type": "agent/inbox/spliced",
                "data": {
                    "inserted": [{
                        "role": "user",
                        "content": [{"type": "text", "text": f"keep unrelated {proseUuid}; session {childId}"}],
                        "source": {"kind": "user"},
                        "id": messageId,
                    }],
                },
            }),
            _dumps({"type": "approval/asked", "data": {"id": approvalId}}),
            _dumps({"type": "tool-workflow/run-start", "data": {"runId": runId}}),
            _dumps({"type": "example", "data": {"requestId": otherId, "echoed": otherId}}),
            "",
        ])
        child = "\n".join([
            _dumps({"type": "session", "id": childId, "parentSession": parentId, "createdAt": 2, "cwd": "/tmp/work"}),
            _dumps({
                "type": "user/message",
                "data": {
                    "role": "user", "content": [], "source": {"kind": "user"}, "id": messageId,
                },
            }),
            "",
        ])

        redacted = redactSessionSnapshotIds([parent, child])
        assert '"id":"{{session:1}}"' in redacted[0]
        assert '"id":"{{session:2}}"' in redacted[1]
        assert '"parentSession":"{{session:1}}"' in redacted[1]
        joined = "\n".join(redacted)
        assert len(re.findall(r"\{\{message:1\}\}", joined)) == 2
        assert '"id":"{{approval:1}}"' in redacted[0]
        assert '"runId":"{{workflow:1}}"' in redacted[0]
        assert '"requestId":"{{id:1}}"' in redacted[0]
        assert '"echoed":"{{id:1}}"' in redacted[0]
        assert proseUuid in redacted[0]
        assert "session {{session:2}}" in redacted[0]
        assert redactSessionSnapshotIds(redacted) == redacted

    def test_classifies_semantic_text_plus_command_rpc_and_retry_identity_fields(self):
        semanticMessage = "88888888-8888-4888-8888-888888888888"
        anonymousUser = "99999999-9999-4999-8999-999999999999"
        retryId = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
        source = "\n".join([
            _dumps({"type": "not-a-session", "data": {"value": "plain"}}),
            _dumps({
                "type": "example",
                "data": {
                    "commandId": "command-7",
                    "rpcId": "rpc-9",
                    "retryId": retryId,
                    "requestId": "stable-readable-id",
                    "text": f"Retain this as message {semanticMessage}. Anonymous user: {anonymousUser}",
                },
            }),
        ])

        redacted_list = redactSessionSnapshotIds([source])
        assert len(redacted_list) == 1
        redacted = redacted_list[0]
        assert '"commandId":"{{command:1}}"' in redacted
        assert '"rpcId":"{{rpc:1}}"' in redacted
        assert '"retryId":"{{retry:1}}"' in redacted
        assert "as message {{message:1}}" in redacted
        assert "Anonymous user: {{id:1}}" in redacted
        assert '"requestId":"stable-readable-id"' in redacted
        assert not redacted.endswith("\n")

    def test_keeps_a_canonical_token_first_seen_through_a_generic_id_key(self):
        canonical = "{{message:7}}"
        nextMessage = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
        source = "\n".join([
            _dumps({"type": "example", "data": {"requestId": canonical}}),
            _dumps({
                "type": "user/message",
                "data": {"role": "user", "content": [], "source": {"kind": "user"}, "id": canonical},
            }),
            _dumps({
                "type": "user/message",
                "data": {"role": "user", "content": [], "source": {"kind": "user"}, "id": nextMessage},
            }),
            "",
        ])

        redacted_list = redactSessionSnapshotIds([source])
        assert len(redacted_list) == 1
        redacted = redacted_list[0]
        assert len(re.findall(r"\{\{message:7\}\}", redacted)) == 2
        assert '"id":"{{message:8}}"' in redacted
        assert "{{id:" not in redacted
