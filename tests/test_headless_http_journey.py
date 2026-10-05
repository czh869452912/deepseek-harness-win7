"""Real launcher -> Loader -> Agent -> editor -> HTTP SSE -> JSONL."""
import json
from jsonl_test_support import read_jsonl_text
import os
from pathlib import Path
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
import yaml

from dsh.boot.profile import init_profile


@pytest.mark.parametrize("truncated,default_profile", [(False, False), (True, False),
    (False, 'headless'), (False, 'standard'), (False, 'creative')])
def test_headless_runner_http_tool_roundtrip_and_exit(tmp_path, truncated, default_profile):
    profile = tmp_path / "home" / "profiles" / "http-journey"
    init_profile(str(profile), [], "startup")
    rows = [{"id": name, "name": "@deepseek-ai/dsh-" + name} for name in (
        "session", "tools", "system-prompt", "agent", "agent-loop", "llm", "llm-deepseek",
        "agent-default-model", "fs-local", "tool-str-replace-editor", "cli-visualizer")]
    for row in rows:
        if row["id"] == "agent-default-model":
            row["config"] = {"provider": "deepseek-official", "model": "chosen-model"}
        if row["id"] == "system-prompt":
            row["config"] = {"persona": "User selected persona"}
        if row["id"] == "cli-visualizer":
            row["config"] = {"verbose": False}
    rows.extend([
        {"id": "persistence", "name": "@deepseek-ai/dsh-session-persistence-jsonl", "config": {"root": str(tmp_path / "sessions")}},
        {"id": "startup", "name": "@deepseek-ai/dsh-headless/startup"},
        {"id": "runner", "name": "@deepseek-ai/dsh-headless", "inject": ["headlessStartup"], "config": {"task": "read the test file"}},
    ])
    (profile / "cordis.patch.yml").write_text(yaml.safe_dump([{"insert": rows}]), encoding="utf-8")
    source = tmp_path / "sample.txt"
    source.write_text("unique file evidence", encoding="utf-8")
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if request.get('tools'):
                requests.append(request)
            if not request.get('tools'):
                delta, finish = {'content': 'Inspect test file'}, 'stop'
            elif len(requests) == 1:
                delta = {"tool_calls": [{"index": 0, "id": "call-read", "type": "function", "function": {
                    "name": "str_replace_editor", "arguments": json.dumps({"command": "view", "path": str(source)})}}]}
                finish = "tool_calls"
            else:
                delta, finish = {"content": "The file contains unique file evidence."}, "stop"
            body = ("data: " + json.dumps({"choices": [{"delta": delta, "finish_reason": finish}]}) + "\n\n").encode("utf-8")
            if not truncated:
                body += b"data: [DONE]\n\n"
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        import sys
        env = dict(os.environ, DSH_HOME=str(tmp_path / "home"), DSH_TELEMETRY_DISABLED="1",
                   DEEPSEEK_API_KEY="local-test-only", DEEPSEEK_BASE_URL="http://127.0.0.1:{}".format(server.server_port))
        result = subprocess.run([sys.executable, str(Path(__file__).resolve().parents[1] / "dsh.py"),
                                 "--profile", default_profile or "http-journey", "inspect"],
                                env=env, cwd=str(tmp_path), capture_output=True, encoding="utf-8", timeout=25)
        if truncated:
            assert result.returncode == 1, result.stdout + result.stderr
            assert "STREAM_CLOSED" in result.stderr
            assert len(requests) == 1
        else:
            assert result.returncode == 0, result.stdout + result.stderr
            assert result.stdout.strip() == "The file contains unique file evidence."
            assert len(requests) == 2
            assert requests[0]["model"] == ("deepseek-v4-flash" if default_profile else "chosen-model")
            if not default_profile:
                assert "User selected persona" in requests[0]["messages"][0]["content"]
            assert requests[0]["tools"][0]["type"] == "function"
            results = [m for m in requests[1]["messages"] if m["role"] == "tool"]
            assert results[0]["tool_call_id"] == "call-read"
            assert "unique file evidence" in results[0]["content"]
            logs = list((tmp_path / ("home/sessions" if default_profile else "sessions")).rglob("*.jsonl.zstd"))
            assert len(logs) == 1
            assert '"tool/result"' in read_jsonl_text(logs[0])
            if default_profile == 'headless':
                repo = Path(__file__).resolve().parents[1]
                session_id = json.loads(read_jsonl_text(logs[0]).splitlines()[0])['id']
                restored = subprocess.run([sys.executable, str(repo / 'tests/headless_resume_process.py'), session_id],
                    cwd=str(tmp_path), env=dict(env, PYTHONPATH=str(repo)), capture_output=True, encoding='utf-8', timeout=25)
                assert restored.returncode == 0, restored.stdout + restored.stderr
                evidence = json.loads(restored.stdout.strip())
                assert evidence['after'] > evidence['before'] > 0
                assert len(requests) == 3
                assert any(message.get('role') == 'tool' and 'unique file evidence' in str(message)
                           for message in requests[2]['messages'])
                assert any(message.get('role') == 'assistant' and 'The file contains' in str(message)
                           for message in requests[2]['messages'])
    finally:
        server.shutdown()
        server.server_close()
        worker.join(2)
