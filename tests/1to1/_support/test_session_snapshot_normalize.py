"""
Unit tests for pure snapshot normalizers.
Ported 1:1 from reference packages/test-support/session-snapshot/tests/normalize.spec.ts.
Compatible with Python 3.8.10 and Windows 7 SP1.
"""

import json
import re
import pytest

from .session_snapshot.normalize import (
    extractSnapshotSpillPaths,
    normalizeSessionLog,
    normalizeSessionSnapshot,
    normalizeSessionSnapshots,
    normalizeStdout,
    scrubRequestHeaders,
    scrubSessionSnapshot,
    scrubSystemPrompts,
    scrubToolSchemas,
    tokenizeSessionFixtureCwd,
)


def _dumps(obj):
    return json.dumps(obj, separators=(",", ":"))


ctx = {
    "sessionIds": ["11111111-2222-3333-4444-555555555555"],
    "cwd": "/tmp/acp-snap-cwd-abc123",
}


class TestNormalizeStdout:
    def test_rewrites_json_rpc_ids_to_a_stable_first_seen_sequence(self):
        raw = "\n".join([
            _dumps({"jsonrpc": "2.0", "id": 42, "method": "initialize"}),
            _dumps({"jsonrpc": "2.0", "id": 42, "result": {}}),
            _dumps({"jsonrpc": "2.0", "id": 99, "method": "session/new"}),
        ])
        out = normalizeStdout(raw, ctx)
        assert '"id":1' in out
        assert '"id":2' in out
        assert "42" not in out
        assert "99" not in out

    def test_scrubs_the_cwd_and_session_id_anywhere_they_appear(self):
        raw = _dumps({
            "jsonrpc": "2.0",
            "method": "session/update",
            "params": {"sessionId": ctx["sessionIds"][0], "cwd": ctx["cwd"], "note": f"at {ctx['cwd']}/x"},
        })
        out = normalizeStdout(raw, ctx)
        assert "{{sessionId}}" in out
        assert "{{cwd}}" in out
        assert ctx["cwd"] not in out
        assert ctx["sessionIds"][0] not in out

    def test_keeps_standard_message_identity_distinct_from_session_identity(self):
        raw = _dumps({
            "jsonrpc": "2.0",
            "method": "session/update",
            "params": {
                "sessionId": ctx["sessionIds"][0],
                "update": {
                    "sessionUpdate": "agent_message_chunk",
                    "messageId": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                    "content": {"type": "text", "text": "done"},
                },
            },
        })
        out = normalizeStdout(raw, ctx)
        assert '"sessionId":"{{sessionId}}"' in out
        assert '"messageId":"{{messageId}}"' in out

    def test_stabilizes_path_dependent_context_occupancy_without_hiding_capacity(self):
        raw = _dumps({
            "jsonrpc": "2.0",
            "method": "session/update",
            "params": {
                "sessionId": ctx["sessionIds"][0],
                "update": {"sessionUpdate": "usage_update", "used": 6438, "size": 1000000},
            },
        })
        frame = json.loads(normalizeStdout(raw, ctx))
        assert frame["params"]["update"] == {
            "sessionUpdate": "usage_update",
            "used": "{{usedTokens}}",
            "size": 1000000,
        }

    def test_scrubs_cwd_at_file_uri_and_chained_punctuation_boundaries(self):
        raw = _dumps({
            "jsonrpc": "2.0",
            "method": "session/update",
            "params": {
                "uri": f"file://{ctx['cwd']}/proof.txt",
                "punctuated": f"{ctx['cwd']}.,",
                "dottedSegment": f"{ctx['cwd']}.backup",
                "dashedSegment": f"{ctx['cwd']}-backup",
            },
        })
        frame = json.loads(normalizeStdout(raw, ctx))
        assert frame["params"] == {
            "uri": "file://{{cwd}}/proof.txt",
            "punctuated": "{{cwd}}.,",
            "dottedSegment": f"{ctx['cwd']}.backup",
            "dashedSegment": f"{ctx['cwd']}-backup",
        }

    def test_scrubs_every_filesystem_spelling_of_the_cwd_longest_first(self):
        long_cwd = r"C:\Users\runneradmin\AppData\Local\Temp\acp-snapshot"
        aliased_ctx = {
            "sessionIds": [],
            "cwd": r"C:\Users\RUNNER~1\AppData\Local\Temp\acp-snapshot",
            "cwdAliases": [
                long_cwd,
                r"C:\Users\runneradmin\AppData\Local\Temp\acp",
            ],
        }
        raw = _dumps({
            "cwd": long_cwd,
            "path": f"{long_cwd}\\nested\\proof.txt",
        })
        frame = json.loads(normalizeStdout(raw, aliased_ctx))
        assert frame == {"cwd": "{{cwd}}", "path": "{{cwd}}/nested/proof.txt"}

    def test_canonicalizes_only_cwd_rooted_path_separators(self):
        windows_ctx = {
            "sessionIds": [],
            "cwd": r"C:\Users\runner\AppData\Local\Temp\acp-snapshot",
        }
        raw = _dumps({
            "jsonrpc": "2.0",
            "method": "session/update",
            "params": {
                "path": f"{windows_ctx['cwd']}\\nested\\proof.txt",
                "regex": r"\d+\w+",
                "command": 'printf "\\n"',
            },
        })
        frame = json.loads(normalizeStdout(raw, windows_ctx))
        assert frame["params"] == {
            "path": "{{cwd}}/nested/proof.txt",
            "regex": r"\d+\w+",
            "command": 'printf "\\n"',
        }

    def test_canonicalizes_generated_relative_path_fields_and_text_markers_without_rewriting_other_text(self):
        raw = _dumps({
            "path": r"nested\AGENTS.md",
            "content": "<path>.\\nested\\task.txt</path>\nAdditional instructions from: nested\\AGENTS.md",
            "regex": r"\d+\w+",
        })
        frame = json.loads(normalizeStdout(raw, {"sessionIds": [], "cwd": "/unused"}))
        assert frame == {
            "path": "nested/AGENTS.md",
            "content": "<path>./nested/task.txt</path>\nAdditional instructions from: nested/AGENTS.md",
            "regex": r"\d+\w+",
        }

    def test_can_preserve_native_cwd_rooted_separators_for_a_platform_golden(self):
        windows_ctx = {"sessionIds": [], "cwd": r"C:\work\snapshot"}
        raw = _dumps({"path": f"{windows_ctx['cwd']}\\nested\\proof.txt"})
        frame = json.loads(normalizeStdout(raw, windows_ctx, {"cwdPathMode": "native"}))
        assert frame["path"] == r"{{cwd}}\nested\proof.txt"

    def test_scrubs_a_stray_uuid_not_in_the_known_list(self):
        raw = _dumps({"jsonrpc": "2.0", "method": "x", "params": {"id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"}})
        assert "{{sessionId}}" in normalizeStdout(raw, ctx)

    def test_leaves_notification_frames_without_an_id_untouched_in_id_space(self):
        raw = _dumps({"jsonrpc": "2.0", "method": "session/update", "params": {}})
        out = normalizeStdout(raw, ctx)
        assert '"id"' not in out

    def test_stabilizes_only_the_top_level_event_timestamp_and_spill_byte_count_in_event_read_text(self):
        raw = _dumps({
            "jsonrpc": "2.0",
            "method": "session/update",
            "params": {
                "update": {
                    "sessionUpdate": "tool_call_update",
                    "content": [{
                        "type": "content",
                        "content": {
                            "type": "text",
                            "text": (
                                "Session prior \u2014 title\n"
                                "Target event seq 4:\n"
                                "```json\n{\n  \"seq\": 4,\n  \"time\": 1784876275593,\n  \"data\": {\n    \"time\": 31337,\n    \"note\": \"model-visible\"\n  }\n}\n```\n\n"
                                "After:\n  \"time\": 424242,\n  neighbor semantic text\n\n"
                                "(Omitted 39387 bytes. Full formatted result stored at: /tmp/result.txt.)"
                            ),
                        },
                    }],
                },
            },
        })
        out = normalizeStdout(raw, ctx)
        assert '\\"time\\": {{eventTime}}' in out
        assert '\\"time\\": 31337' in out
        assert '\\"time\\": 424242' in out
        assert "Omitted {{eventOmittedBytes}} bytes" in out
        assert "1784876275593" not in out
        assert "39387" not in out

    def test_preserves_event_like_timestamps_in_unrelated_output_text(self):
        raw = _dumps({
            "jsonrpc": "2.0",
            "method": "session/update",
            "params": {
                "update": {
                    "sessionUpdate": "tool_call_update",
                    "content": [{
                        "type": "content",
                        "content": {
                            "type": "text",
                            "text": (
                                "bash output:\n```json\n{\n  \"time\": 1784876275593,\n  \"data\": {}\n}\n```\n\n"
                                "(Omitted 39387 bytes. Full formatted result stored at: /tmp/result.txt.)"
                            ),
                        },
                    }],
                },
            },
        })
        out = normalizeStdout(raw, ctx)
        assert "1784876275593" in out
        assert "39387" in out
        assert "{{eventTime}}" not in out
        assert "{{eventOmittedBytes}}" not in out

    def test_throws_on_a_non_json_stdout_line_the_purity_check(self):
        raw = f"{_dumps({'jsonrpc': '2.0', 'id': 1})}\noops a log leaked\n"
        with pytest.raises(Exception):
            normalizeStdout(raw, ctx)

    def test_ignores_blank_lines(self):
        raw = f"\n{_dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'm'})}\n\n"
        normalizeStdout(raw, ctx)


class TestNormalizeSessionLog:
    def _header(self, over=None):
        base = {"type": "session", "version": 0, "id": "s", "createdAt": 123}
        if over:
            base.update(over)
        return _dumps(base)

    def _event(self, over=None):
        base = {"type": "turn/start", "seq": 1, "time": 999, "data": {"turn": 1}}
        if over:
            base.update(over)
        return _dumps(base)

    def test_zeroes_the_header_created_at(self):
        out = normalizeSessionLog(f"{self._header()}\n", ctx)
        assert '"createdAt":0' in out
        assert "123" not in out

    def test_preserves_event_sequence_and_zeroes_event_time(self):
        out = normalizeSessionLog(f"{self._header()}\n{self._event({'seq': 7, 'time': 999})}\n", ctx)
        assert '"time":0' in out
        assert '"seq":7' in out
        assert "999" not in out

    def test_normalizes_a_projected_event_without_adding_a_persistence_envelope(self):
        projected = _dumps({"type": "turn/start", "data": {"turn": 1}})
        out = normalizeSessionLog(f"{self._header()}\n{projected}\n", ctx)
        second_line = out.rstrip().split("\n")[1]
        assert json.loads(second_line) == {"type": "turn/start", "data": {"turn": 1}}

    def test_scrubs_cwd_and_session_id_deep_inside_event_data(self):
        ev = _dumps({
            "type": "tool/result", "seq": 2, "time": 5,
            "data": {"content": [{"type": "text", "text": f"wrote {ctx['cwd']}/proof.txt"}]},
        })
        out = normalizeSessionLog(f"{self._header({'cwd': ctx['cwd']})}\n{ev}\n", ctx)
        assert "{{cwd}}" in out
        assert ctx["cwd"] not in out

    def test_scrubs_cwd_at_file_uri_and_chained_punctuation_boundaries_in_event_data(self):
        ev = _dumps({
            "type": "tool/result",
            "seq": 2,
            "time": 5,
            "data": {
                "uri": f"file://{ctx['cwd']}/proof.txt",
                "punctuated": f"{ctx['cwd']}.,",
            },
        })
        out = normalizeSessionLog(f"{self._header({'cwd': ctx['cwd']})}\n{ev}\n", ctx)
        assert "file://{{cwd}}/proof.txt" in out
        assert "{{cwd}}.," in out
        assert f"file://{ctx['cwd']}" not in out

    def test_scrubs_random_local_spill_paths_under_the_snapshot_cwd(self):
        ev = _dumps({
            "type": "tool/result", "seq": 2, "time": 5,
            "data": {
                "content": [{
                    "type": "text",
                    "text": f"Full formatted result stored at: {ctx['cwd']}/.spill/session-c22bc3f1d2af/8a7b6c5d4e3f-bash.txt. Use read with offset/limit, or grep this path to search within it.",
                }],
            },
        })
        out = normalizeSessionLog(f"{self._header({'cwd': ctx['cwd']})}\n{ev}\n", ctx)
        assert "{{spillLocator:bash.txt}}" in out
        assert "session-c22bc3f1d2af" not in out
        assert "8a7b6c5d4e3f" not in out

    def test_scrubs_macos_private_aliases_for_local_spill_paths(self):
        ev = _dumps({
            "type": "tool/result", "seq": 2, "time": 5,
            "data": {
                "content": [{
                    "type": "text",
                    "text": f"Full formatted result stored at: /private{ctx['cwd']}/.spill/session-c22bc3f1d2af/8a7b6c5d4e3f-bash.txt. Use read with offset/limit, or grep this path to search within it.",
                }],
            },
        })
        out = normalizeSessionLog(f"{self._header({'cwd': ctx['cwd']})}\n{ev}\n", ctx)
        assert "{{spillLocator:bash.txt}}" in out
        assert "/private{{spillLocator" not in out

    def test_scrubs_macos_private_prefix_on_cwd_rooted_fs_tool_result_paths(self):
        ev = _dumps({
            "type": "tool/result", "seq": 2, "time": 5,
            "data": {
                "content": [{
                    "type": "text",
                    "text": f"The file /private{ctx['cwd']}/config.txt has been updated successfully.",
                }],
            },
        })
        out = normalizeSessionLog(f"{self._header({'cwd': ctx['cwd']})}\n{ev}\n", ctx)
        assert "{{cwd}}/config.txt" in out
        assert "/private{{cwd}}" not in out

    def test_scrubs_fixed_snapshot_spill_paths(self):
        ev = _dumps({
            "type": "tool/result", "seq": 2, "time": 5,
            "data": {
                "content": [{
                    "type": "text",
                    "text": "Full formatted result stored at: /tmp/dsh-acp-snapshot-spill/session-c22bc3f1d2af/8a7b6c5d4e3f-bash.txt. Use read with offset/limit, or grep this path to search within it.",
                }],
            },
        })
        out = normalizeSessionLog(f"{self._header({'cwd': ctx['cwd']})}\n{ev}\n", ctx)
        assert "{{spillLocator:bash.txt}}" in out
        assert "/tmp/dsh-acp-snapshot-spill" not in out

    def test_scrubs_scenario_owned_snapshot_spill_paths(self):
        ev = _dumps({
            "type": "tool/result", "seq": 2, "time": 5,
            "data": {
                "content": [{
                    "type": "text",
                    "text": "Full formatted result stored at: /tmp/dsh-acp-snap-012345678/session-c22bc3f1d2af/8a7b6c5d4e3f-bash.txt. Use read with offset/limit, or grep this path to search within it.",
                }],
            },
        })
        out = normalizeSessionLog(f"{self._header({'cwd': ctx['cwd']})}\n{ev}\n", ctx)
        assert "{{spillLocator:bash.txt}}" in out
        assert "/tmp/dsh-acp-snap-012345678" not in out

    def test_scrubs_scenario_owned_snapshot_spill_paths_with_windows_drive_and_separators(self):
        ev = _dumps({
            "type": "tool/result", "seq": 2, "time": 5,
            "data": {
                "content": [{
                    "type": "text",
                    "text": r"Full formatted result stored at: C:\t\dsh-acp-snap-012345678\session-c22bc3f1d2af\8a7b6c5d4e3f-bash.txt. Use read with offset/limit, or grep this path to search within it.",
                }],
            },
        })
        out = normalizeSessionLog(f"{self._header({'cwd': ctx['cwd']})}\n{ev}\n", ctx)
        assert "{{spillLocator:bash.txt}}" in out
        assert r"C:\t\dsh-acp-snap-012345678" not in out

    def test_shares_cwd_rooted_path_handling_with_stdout_normalization(self):
        windows_ctx = {"sessionIds": [], "cwd": r"C:\work\snapshot"}
        ev = _dumps({
            "type": "tool/result", "seq": 2, "time": 5,
            "data": {"path": f"{windows_ctx['cwd']}\\nested\\proof.txt"},
        })
        assert "{{cwd}}/nested/proof.txt" in normalizeSessionLog(
            f"{self._header({'cwd': windows_ctx['cwd']})}\n{ev}\n", windows_ctx
        )
        assert r"{{cwd}}\\nested\\proof.txt" in normalizeSessionLog(
            f"{self._header({'cwd': windows_ctx['cwd']})}\n{ev}\n", windows_ctx, {"cwdPathMode": "native"}
        )

    def test_scrubs_the_session_id_in_the_header(self):
        out = normalizeSessionLog(f"{self._header({'id': ctx['sessionIds'][0]})}\n", ctx)
        assert "{{sessionId}}" in out

    def test_zeroes_a_hook_result_duration_ms_run_to_run_noise_but_keeps_its_decision(self):
        ev = _dumps({
            "type": "hook/result", "seq": 2, "time": 5,
            "data": {"turn": 1, "point": "UserPromptSubmit", "handlerId": "h", "decision": "block", "exitCode": 2, "durationMs": 37},
        })
        out = normalizeSessionLog(f"{self._header()}\n{ev}\n", ctx)
        assert '"durationMs":0' in out
        assert "37" not in out
        assert '"decision":"block"' in out

    def test_preserves_a_packed_chunk_rows_sequence_zeroes_time_and_zeroes_volatile_dt_gaps(self):
        row = _dumps({
            "type": "text-chunks", "seq0": 7, "time0": 999,
            "data": {"turn": 1, "step": 1, "index": 0, "dt": [212, 27, 0], "texts": ["a", "b", "c", "d"]},
        })
        out = normalizeSessionLog(f"{self._header()}\n{row}\n", ctx)
        assert '"time0":0' in out
        assert '"dt":[0,0,0]' in out
        assert '"seq0":7' in out
        assert '"texts":["a","b","c","d"]' in out
        assert "999" not in out
        assert "212" not in out

    def test_normalizes_a_headerless_packed_like_stream_record_without_decoding_it(self):
        row = _dumps({"type": "text-chunks", "seq0": 1, "time0": 999, "data": "not-an-object"})
        out = normalizeSessionLog(f"{row}\n", ctx)
        assert '"seq0":1' in out
        assert '"time0":0' in out

    def test_leaves_a_non_hook_event_duration_ms_untouched_only_hook_result_is_scrubbed(self):
        ev = _dumps({"type": "tool/result", "seq": 2, "time": 5, "data": {"durationMs": 88}})
        out = normalizeSessionLog(f"{self._header()}\n{ev}\n", ctx)
        assert '"durationMs":88' in out

    def test_normalizes_goal_lifecycle_clocks_without_scrubbing_unrelated_payload_timestamps(self):
        goal = _dumps({
            "type": "goal/change",
            "seq": 2,
            "time": 5,
            "data": {"operation": "create", "createdAt": 123, "updatedAt": 124},
        })
        tool = _dumps({"type": "tool/result", "seq": 3, "time": 6, "data": {"createdAt": 125}})
        goal_without_clocks = _dumps({"type": "goal/change", "seq": 4, "time": 7, "data": {"operation": "resume"}})
        out = normalizeSessionLog(f"{self._header()}\n{goal}\n{tool}\n{goal_without_clocks}\n", ctx)
        assert '"operation":"create","createdAt":0,"updatedAt":0' in out
        assert '"createdAt":125' in out
        assert '"operation":"resume"' in out

    def test_handles_complete_envelopes_when_optional_normalized_fields_are_absent(self):
        bare_header = _dumps({"type": "session", "id": "s"})
        bare_hook = _dumps({"type": "hook/result", "seq": 2, "time": 5, "data": {"decision": "allow"}})
        null_data_hook = _dumps({"type": "hook/result", "seq": 3, "time": 6, "data": None})
        out = normalizeSessionLog(f"{bare_header}\n{bare_hook}\n{null_data_hook}\n", ctx)
        assert '"decision":"allow"' in out
        assert "durationMs" not in out


class TestNormalizeSessionSnapshot:
    def test_normalizes_scrubs_and_projects_each_parsed_body_record(self):
        raw = "\n".join([
            _dumps({"type": "session", "version": 0, "createdAt": 123, "cwd": ctx["cwd"]}),
            _dumps({
                "type": "request/header",
                "seq": 7,
                "time": 999,
                "data": {"header": {"system": "volatile", "tools": [{"name": "tool"}]}},
            }),
        ]) + "\n"
        expected = "\n".join([
            _dumps({"type": "session", "version": 0, "createdAt": 0, "cwd": "{{cwd}}"}),
            _dumps({"type": "request/header", "data": {"header": {"system": "{{system}}", "tools": "{{tools}}"}}}),
        ]) + "\n"
        assert normalizeSessionSnapshot(raw, ctx) == expected

    def test_normalizes_an_already_projected_packed_row(self):
        raw = "\n".join([
            _dumps({"type": "session", "version": 0}),
            _dumps({
                "type": "text-chunks",
                "data": {"turn": 1, "step": 1, "index": 0, "dt": [9, 8], "texts": ["a", "b", "c"]},
            }),
        ]) + "\n"
        assert '"dt":[0,0]' in normalizeSessionSnapshot(raw, ctx)

    def test_re_packs_adjacent_chunk_runs_split_by_persistence_flushes(self):
        raw = "\n".join([
            _dumps({"type": "session", "version": 0}),
            _dumps({
                "type": "text-chunks",
                "data": {"turn": 1, "step": 1, "index": 0, "dt": [4, 5], "texts": ["a", "b", "c"]},
            }),
            _dumps({
                "type": "text-chunks",
                "data": {"turn": 1, "step": 1, "index": 0, "dt": [6, 7], "texts": ["d", "e", "f"]},
            }),
        ]) + "\n"
        expected = "\n".join([
            _dumps({"type": "session", "version": 0}),
            _dumps({
                "type": "text-chunks",
                "data": {"turn": 1, "step": 1, "index": 0, "dt": [0, 0, 0, 0, 0], "texts": ["a", "b", "c", "d", "e", "f"]},
            }),
            "",
        ])
        assert normalizeSessionSnapshot(raw, ctx) == expected

    def test_re_packs_multi_session_fixtures_after_relationship_preserving_id_redaction(self):
        raw = "\n".join([
            _dumps({"type": "session", "version": 0}),
            _dumps({
                "type": "reasoning-chunks",
                "data": {"turn": 1, "step": 1, "index": 0, "dt": [1, 2], "texts": ["a", "b", "c"]},
            }),
            _dumps({
                "type": "reasoning-chunks",
                "data": {"turn": 1, "step": 1, "index": 0, "dt": [3, 4], "texts": ["d", "e", "f"]},
            }),
        ]) + "\n"
        expected = [
            "\n".join([
                _dumps({"type": "session", "version": 0}),
                _dumps({
                    "type": "reasoning-chunks",
                    "data": {"turn": 1, "step": 1, "index": 0, "dt": [0, 0, 0, 0, 0], "texts": ["a", "b", "c", "d", "e", "f"]},
                }),
                "",
            ])
        ]
        assert normalizeSessionSnapshots([raw], ctx) == expected

    def test_projects_persisted_provenance_ranges_back_to_logical_seq_arrays(self):
        raw = "\n".join([
            _dumps({"type": "session", "version": 0}),
            _dumps({
                "type": "assistant/message",
                "sourceEventSeqs": [[1, 3], 5],
                "surfaceOp": "append",
                "data": {"turn": 1, "step": 1},
            }),
        ]) + "\n"
        assert '"sourceEventSeqs":[1,2,3,5]' in normalizeSessionSnapshot(raw, ctx)

    def test_rejects_headerless_input(self):
        with pytest.raises(Exception) as excinfo:
            normalizeSessionSnapshot('{"type":"turn/start"}\n', ctx)
        assert "session snapshot must start with a session header" in str(excinfo.value)


class TestTokenizeSessionFixtureCwd:
    @pytest.mark.parametrize("name,context,reported_cwd", [
        (
            "macOS",
            {
                "sessionIds": [],
                "cwd": "/var/folders/2g/snapshot/T/acp-snap-cwd-abc123",
                "cwdAliases": ["/private/var/folders/2g/snapshot/T/acp-snap-cwd-abc123"],
            },
            "/private/var/folders/2g/snapshot/T/acp-snap-cwd-abc123",
        ),
        (
            "Linux",
            {
                "sessionIds": [],
                "cwd": "/tmp/acp-snap-cwd-abc123",
            },
            "/tmp/acp-snap-cwd-abc123",
        ),
        (
            "Windows",
            {
                "sessionIds": [],
                "cwd": r"C:\Users\runner\AppData\Local\Temp\acp-snap-cwd-abc123",
            },
            r"C:\Users\runner\AppData\Local\Temp\acp-snap-cwd-abc123",
        ),
    ])
    def test_stores_temporary_workspaces_with_one_portable_root_token(self, name, context, reported_cwd):
        raw = "\n".join([
            _dumps({"type": "session", "id": "s", "createdAt": 1, "cwd": context["cwd"]}),
            _dumps({
                "type": "tool/result",
                "seq": 1,
                "time": 2,
                "data": {
                    "content": [{
                        "type": "text",
                        "text": f"wrote {reported_cwd}/proof.txt. alias /different/root/acp-snap-cwd-abc123/alias.txt. cwd {context['cwd']}. Next; kept {context['cwd']}-backup, {context['cwd']}.backup, and /tmp/authored.txt",
                    }],
                },
            }),
            "",
        ])

        out = tokenizeSessionFixtureCwd(raw)
        result = json.loads(out.split("\n")[1])
        result_text = result["data"]["content"][0]["text"]

        assert '"cwd":"{{cwd}}"' in out
        assert "wrote {{cwd}}/proof.txt" in result_text
        assert "alias {{cwd}}/alias.txt" in result_text
        assert "cwd {{cwd}}. Next" in result_text
        assert f"{context['cwd']}-backup" in result_text
        assert f"{context['cwd']}.backup" in result_text
        assert "/tmp/authored.txt" in result_text
        assert f"{reported_cwd}/proof.txt" not in result_text
        assert tokenizeSessionFixtureCwd(out) == out

    def test_collapses_a_residual_macos_realpath_prefix_around_an_existing_cwd_token(self):
        raw = "\n".join([
            _dumps({"type": "session", "id": "s", "createdAt": 1, "cwd": "{{cwd}}"}),
            _dumps({
                "type": "tool/result",
                "seq": 1,
                "time": 2,
                "data": {"content": [{"type": "text", "text": "wrote /private{{cwd}}/proof.txt"}]},
            }),
            "",
        ])
        out = tokenizeSessionFixtureCwd(raw)
        assert "wrote {{cwd}}/proof.txt" in out
        assert "/private{{cwd}}" not in out
        assert tokenizeSessionFixtureCwd(out) == out

    def test_rejects_a_log_without_a_session_cwd(self):
        with pytest.raises(Exception) as excinfo:
            tokenizeSessionFixtureCwd("")
        assert "acp-snapshot: cannot tokenize a cwd without a basename" in str(excinfo.value)


class TestExtractSnapshotSpillPaths:
    def test_maps_each_spill_filename_to_its_full_matched_path_last_match_wins_per_name(self):
        log = "\n".join([
            "Full formatted result stored at: /tmp/dsh-acp-snapshot-spill/session-c22bc3f1d2af/8a7b6c5d4e3f-bash.txt. Use read with offset/limit, or grep this path to search within it.",
            "stale copy at /tmp/dsh-acp-snap-012345678/session-aaaaaaaaaaaa/bbbbbbbbbbbb-grep.txt then",
            "fresh copy at /tmp/dsh-acp-snap-012345678/session-cccccccccccc/dddddddddddd-grep.txt then",
        ])
        assert extractSnapshotSpillPaths(log) == {
            "bash.txt": "/tmp/dsh-acp-snapshot-spill/session-c22bc3f1d2af/8a7b6c5d4e3f-bash.txt",
            "grep.txt": "/tmp/dsh-acp-snap-012345678/session-cccccccccccc/dddddddddddd-grep.txt",
        }

    def test_returns_an_empty_map_when_the_log_carries_no_snapshot_spill_paths(self):
        assert extractSnapshotSpillPaths("no spill paths here, only /tmp/other.txt\n") == {}


class TestScrubRequestHeaders:
    header_line = _dumps({"type": "session", "version": 0, "id": "s", "createdAt": 1, "cwd": "/w"})

    def _header_event(self, header):
        return _dumps({"type": "request/header", "seq": 3, "time": 9, "data": {"header": header, "reason": "initial"}})

    def test_replaces_header_system_and_tools_with_tokens_keeping_config_and_reason(self):
        ev = self._header_event({
            "config": {"model": "m"},
            "system": "You are an agent.\nBe brief.",
            "tools": [{"name": "read", "description": "Read a file.", "parameters": {"type": "object"}}],
        })
        out = scrubRequestHeaders(f"{self.header_line}\n{ev}\n")
        assert '"system":"{{system}}"' in out
        assert '"tools":"{{tools}}"' in out
        assert '"config":{"model":"m"}' in out
        assert '"reason":"initial"' in out
        assert "You are an agent" not in out
        assert "Read a file" not in out

    def test_keeps_an_absent_system_tools_absent_presence_is_behavior(self):
        out = scrubRequestHeaders(f"{self.header_line}\n{self._header_event({'config': {'model': 'm'}})}\n")
        assert "{{system}}" not in out
        assert "{{tools}}" not in out

    def test_scrubs_a_header_carrying_only_one_of_system_tools_leaving_the_other_absent(self):
        system_only = scrubRequestHeaders(f"{self.header_line}\n{self._header_event({'system': 'secret prompt'})}\n")
        assert '"system":"{{system}}"' in system_only
        assert "{{tools}}" not in system_only

        tools_only = scrubRequestHeaders(f"{self.header_line}\n{self._header_event({'tools': [{'name': 't'}]})}\n")
        assert '"tools":"{{tools}}"' in tools_only
        assert "{{system}}" not in tools_only

    def test_leaves_malformed_headers_with_no_scrubbable_payload_byte_identical(self):
        headerless = _dumps({"type": "request/header", "seq": 10, "time": 9, "data": {"reason": "initial"}})
        null_data = _dumps({"type": "request/header", "seq": 11, "time": 9, "data": None})
        raw = f"{self.header_line}\n{headerless}\n{null_data}\n"
        assert scrubRequestHeaders(raw) == raw

    def test_passes_every_other_line_through_byte_for_byte_and_is_idempotent(self):
        other = _dumps({"type": "assistant/chunk", "seq": 4, "time": 9, "data": {"turn": 1, "step": 1, "chunk": {"type": "text-delta", "index": 0, "text": "hi"}}})
        raw = f"{self.header_line}\n{self._header_event({'config': {'model': 'm'}, 'system': 's', 'tools': []})}\n{other}\n"
        once = scrubRequestHeaders(raw)
        assert once.split("\n")[0] == self.header_line
        assert once.split("\n")[2] == other
        assert scrubRequestHeaders(once) == once


class TestScrubSessionSnapshot:
    def test_preserves_the_header_while_projecting_and_scrubbing_each_body_record(self):
        header = '  {"type":"session","version":0,"id":"s","createdAt":7}  '
        request = _dumps({
            "type": "request/header", "seq": 0, "time": 9,
            "data": {"header": {"system": "secret", "tools": [{"name": "read"}]}, "reason": "initial"},
        })
        event = _dumps({
            "type": "turn/start", "seq": 1, "time": 10,
            "data": {"turn": 1, "seq": 41, "time": 42},
        })
        expected = "\n".join([
            header,
            '{"type":"request/header","data":{"header":{"system":"{{system}}","tools":"{{tools}}"},"reason":"initial"}}',
            '{"type":"turn/start","data":{"turn":1,"seq":41,"time":42}}',
            "",
        ])
        assert scrubSessionSnapshot(f"{header}\n{request}\n{event}\n") == expected

    def test_rejects_headerless_input(self):
        with pytest.raises(Exception) as excinfo:
            scrubSessionSnapshot('{"type":"turn/start"}\n')
        assert "session snapshot must start with a session header" in str(excinfo.value)


class TestScrubSystemPrompts:
    def test_scrubs_only_system_prompt_payloads_while_keeping_tools_verbatim(self):
        header = _dumps({
            "type": "request/header", "seq": 1, "time": 2,
            "data": {
                "header": {
                    "system": "full prompt",
                    "tools": [{"name": "read", "description": "full schema"}],
                },
                "reason": "initial",
            },
        })
        changed = _dumps({
            "type": "request/header", "seq": 2, "time": 3,
            "data": {
                "header": {
                    "system": "new prompt",
                    "tools": [{"name": "read", "description": "changed schema"}],
                },
                "reason": "change",
            },
        })
        tools_only = _dumps({
            "type": "request/header", "seq": 3, "time": 4,
            "data": {"header": {"tools": [{"name": "read", "description": "schema only"}]}, "reason": "resume"},
        })

        out = scrubSystemPrompts(f"{header}\n{changed}\n{tools_only}\n")
        assert '"system":"{{system}}"' in out
        assert "full prompt" not in out
        assert "new prompt" not in out
        assert "full schema" in out
        assert "changed schema" in out
        assert out.split("\n")[2] == tools_only
        assert scrubSystemPrompts(out) == out


class TestScrubToolSchemas:
    def test_scrubs_only_tool_schema_payloads_while_keeping_prompts_verbatim(self):
        header = _dumps({
            "type": "request/header", "seq": 1, "time": 2,
            "data": {
                "header": {
                    "system": "full prompt",
                    "tools": [{"name": "read", "description": "full schema", "parameters": {"type": "object"}}],
                },
                "reason": "initial",
            },
        })
        changed = _dumps({
            "type": "request/header", "seq": 2, "time": 3,
            "data": {
                "header": {
                    "system": "new prompt",
                    "tools": [{"name": "grep", "description": "new schema"}],
                },
                "reason": "change",
            },
        })
        system_only = _dumps({
            "type": "request/header", "seq": 3, "time": 4,
            "data": {"header": {"system": "prompt only"}, "reason": "resume"},
        })

        out = scrubToolSchemas(f"{header}\n{changed}\n{system_only}\n")
        assert len(re.findall(r'"tools":"\{\{tools\}\}"', out)) == 2
        assert "full schema" not in out
        assert "new schema" not in out
        assert "full prompt" in out
        assert "new prompt" in out
        assert out.split("\n")[2] == system_only
        assert scrubToolSchemas(out) == out
