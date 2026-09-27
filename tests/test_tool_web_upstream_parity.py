import asyncio
import time
from types import SimpleNamespace

import pytest

from dsh.cordis.context import Context
from dsh.core.tools import ToolExecutionInput, ToolsService
from dsh.web.tool_web import ToolWebPlugin
from dsh.web.tool_web.fetch import (
    fetch_meta_from_result,
    fetch_meta_from_value,
    format_fetch_output,
    parse_fetch_args,
    present_fetch_call,
)
from dsh.web.tool_web.search import (
    format_search_output,
    parse_search_args,
    present_search_call,
    search_meta_from_result,
    search_meta_from_value,
)
from dsh.web.web_service import WebFetchProvider, WebSearchProvider, WebService


class PromptService:
    def __init__(self):
        self.sections = {}

    def section(self, *args, **kwargs):
        value = args[0] if args and isinstance(args[0], dict) else dict(kwargs)
        self.sections[value["name"]] = value

        def dispose():
            self.sections.pop(value["name"], None)

        return dispose


async def mount(web, config=None):
    ctx = Context()
    tools = ToolsService(ctx)
    prompt = PromptService()
    ctx.set_service("tools", tools)
    ctx.set_service("web", web)
    ctx.set_service("systemPrompt", prompt)
    fiber = ctx.registry.plugin(ToolWebPlugin, config or {}, parent_ctx=ctx)
    await fiber
    return ctx, tools, prompt, fiber


def content_text(result):
    return "".join(block["text"] for block in result.content if block["type"] == "text")


def test_search_pure_contract_and_meta_narrowing():
    assert parse_search_args({"queries": ["one", "one", " two "]}, 4) == ["one", " two "]
    with pytest.raises(ValueError, match="at least one"):
        parse_search_args({"queries": []}, 4)
    with pytest.raises(ValueError, match="at most 1 query"):
        parse_search_args({"queries": ["one", "two"]}, 1)
    with pytest.raises(ValueError, match="each query"):
        parse_search_args({"queries": ["ok", " "]}, 4)
    value = {"content": "answer", "sources": [
        {"url": "https://a.test/x", "title": "A", "snippet": "snip", "publishedAt": "2026-01-01"},
        {"url": "https://b.test/y"},
    ], "truncated": True}
    rendered = format_search_output(value)
    assert "[A](https://a.test/x) \u2014 snip (2026-01-01)" in rendered
    assert "[b.test](https://b.test/y)" in rendered
    assert "Showing the first 2 sources" in rendered
    assert present_search_call({"queries": ["one", "two"]})["title"] == "one, two"
    meta = search_meta_from_value(value)
    assert meta["answer"] == "answer"
    assert search_meta_from_result(meta) == meta
    assert search_meta_from_result({"sources": [{"url": 1}], "truncated": False}) is None


def test_fetch_format_html_text_cap_and_meta():
    assert parse_fetch_args({"url": "https://a.test"}) == {"url": "https://a.test"}
    with pytest.raises(ValueError, match="non-empty"):
        parse_fetch_args({"url": " "})
    html_value = {"url": "https://a.test", "statusCode": 200,
                  "body": {"kind": "html", "content": "<h1>Title</h1><p>Hello <strong>world</strong></p><script>bad()</script>"},
                  "truncated": False}
    output = format_fetch_output(html_value, 1000)
    assert output.startswith("Fetched https://a.test (HTTP 200)\n\n# Title")
    assert "**world**" in output and "bad()" not in output
    tiny = format_fetch_output({"url": "https://a.test", "statusCode": 200,
                                "body": {"kind": "text", "content": "abcdef"},
                                "truncated": True}, 10)
    assert tiny == "Fetched ht"
    capped = format_fetch_output({"url": "https://a.test", "statusCode": 200,
                                  "body": {"kind": "text", "content": "x" * 1000},
                                  "truncated": False}, 100)
    assert len(capped) == 100 and "Content truncated" in capped
    meta = fetch_meta_from_value(html_value, 1000)
    assert meta == {"url": "https://a.test", "statusCode": 200, "truncated": False}
    assert fetch_meta_from_result(meta) == meta
    assert fetch_meta_from_result({"url": "u", "statusCode": "200", "truncated": False}) is None
    assert present_fetch_call({"url": "https://a.test"})["kind"] == "fetch"


def test_fetch_gfm_table_and_deep_html_fallback():
    value = {"url": "https://a.test", "statusCode": 200, "truncated": False,
             "body": {"kind": "html", "content":
                      '<table><tr><th align="left">A</th><th align="right">B</th></tr>'
                      '<tr><td>1</td><td>2</td></tr></table>'}}
    output = format_fetch_output(value, 10000)
    assert "| A   | B   |\n| :--- | ---: |\n| 1   | 2   |" in output
    pathological = "<div>" * 513 + "x" + "</div>" * 513
    raw = format_fetch_output({"url": "https://a.test", "statusCode": 200,
                               "body": {"kind": "html", "content": pathological},
                               "truncated": False}, 100000)
    assert raw.endswith(pathological)
    boundary = "<div>" * 512 + "x" + "</div>" * 512
    assert _render_html(boundary) == "x"
    styled = format_fetch_output({"url": "https://a.test", "statusCode": 200,
                                  "body": {"kind": "html", "content":
                                           "<h2>Heading</h2><ul><li>one_two</li><li>three</li></ul>"},
                                  "truncated": False}, 10000)
    assert "## Heading\n\n-   one\\_two\n-   three" in styled
    quoted = format_fetch_output({"url": "https://a.test", "statusCode": 200,
                                  "body": {"kind": "html", "content":
                                           "<p><strong>bold <em>italic</em></strong></p><blockquote><p>quoted</p></blockquote>"},
                                  "truncated": False}, 10000)
    assert "**bold _italic_**\n\n> quoted" in quoted
    script_markup = "<script>const x = '%s'</script><p>safe</p>" % ("<div>" * 600)
    script_output = format_fetch_output({"url": "https://a.test", "statusCode": 200,
                                         "body": {"kind": "html", "content": script_markup},
                                         "truncated": False}, 100000)
    assert script_output.endswith("safe")
    assert "<script>" not in script_output


def test_fetch_comment_state_malformed_bound_and_additional_gfm_rules():
    comment = "<div><!-- </div><span>hidden</span> --><p>safe</p></div>"
    assert _render_html(comment) == "safe"
    assert _render_html("<p>safe</p><!-- unfinished") == "safe"

    malformed = "<a" * 100000
    started = time.monotonic()
    rendered = _render_html(malformed)
    assert time.monotonic() - started < 2.0
    assert rendered.startswith("<a<a<a")
    assert rendered.endswith("(Content truncated. Fetch a more specific URL or section for the full text.)")

    assert _render_html(
        "<ul><li><input type='checkbox' checked> done</li>"
        "<li><input type='checkbox'> todo</li></ul>"
    ) == "-   [x]  done\n-   [ ]  todo"
    assert _render_html(
        "<div class='highlight highlight-source-python'><pre>print(1)</pre></div>"
    ) == "```python\nprint(1)\n```"
    assert _render_html(
        "<table><tr><td>A</td><td>B</td></tr>"
        "<tr><td>1</td><td>2</td></tr></table>"
    ) == "|     |     |\n| --- | --- |\n| A   | B   |\n| 1   | 2   |"


def _render_html(html):
    header = "Fetched https://a.test (HTTP 200)\n\n"
    value = {"url": "https://a.test", "statusCode": 200, "truncated": False,
             "body": {"kind": "html", "content": html}}
    return format_fetch_output(value, 100000)[len(header):]


@pytest.mark.parametrize("html, expected", [
    ("<pre><code class='language-python'>print(`x`)\n```\n</code></pre>",
     "````python\nprint(`x`)\n```\n````"),
    ("<p><code>a`b</code> and <del>gone</del></p>",
     "``a`b`` and ~~gone~~"),
    ("<p><img src='x.png' alt='A [pic]' title='T'></p><hr>",
     '![A \\[pic\\]](x.png "T")\n\n* * *'),
    ("<ol start='3'><li>three</li><li>four<ul><li>nested</li></ul></li></ol>",
     "3.  three\n4.  four\n    -   nested"),
    ("<h2>H</h2><blockquote><p>one</p><p>two</p></blockquote>"
     "<p><a href='https://x' title='T'><strong>bold</strong></a></p>",
     '## H\n\n> one\n> \n> two\n\n[**bold**](https://x "T")'),
    ("<table><tr><th><strong>A</strong></th><th><code>B</code></th></tr>"
     "<tr><td><em>x</em></td><td><del>y</del></td></tr></table>",
     "| **A** | `B` |\n| --- | --- |\n| _x_ | ~~y~~ |"),
    ("<p># head\n- item\n1. ordered\n> quote\n[brackets] * star _ under ` tick \\ slash</p>",
     "\\# head - item 1. ordered > quote \\[brackets\\] \\* star \\_ under \\` tick \\\\ slash"),
    ("<p>1. ordered</p><p>1) plain</p><p>---</p>",
     "1\\. ordered\n\n1) plain\n\n\\---"),
    ("<p>&lt; &gt; &amp; &quot; &#39; &copy; &nbsp;</p>", '< > & " \' (c)'.replace("(c)", "©")),
])
def test_fetch_html_matches_turndown_gfm_rules(html, expected):
    assert _render_html(html) == expected


class CanonicalWeb:
    def __init__(self):
        self.search_calls = []
        self.fetch_calls = []

    async def search(self, request, signal):
        self.search_calls.append((request, signal))
        query = request["query"]
        return {"content": "answer " + query,
                "sources": [{"url": "https://%s.test" % query}, {"url": "https://shared.test"}],
                "truncated": False}

    async def fetch(self, request, signal):
        self.fetch_calls.append((request, signal))
        return {"url": request["url"], "statusCode": 404,
                "body": {"kind": "text", "content": "not found"}, "truncated": False}


@pytest.mark.asyncio
async def test_registration_prompt_canonical_execution_signal_merge_and_disposal():
    web = CanonicalWeb()
    ctx, tools, prompt, fiber = await mount(web, {"searchMaxResults": 2, "searchMaxQueries": 2})
    try:
        assert ToolWebPlugin.inject == ["tools", "web", "systemPrompt"]
        assert set(prompt.sections) == {"tool:web_search", "tool:web_fetch"}
        search = tools.get_tool("web_search")
        fetch = tools.get_tool("web_fetch")
        assert search.canonical and fetch.canonical
        assert search.timeout_ms == 30000 and fetch.timeout_ms == 30000
        assert tools.execution_mode(ToolExecutionInput(
            "m", "web_search", {"queries": ["one"]}, signal=asyncio.Event()
        )) == {"kind": "parallel"}
        signal = asyncio.Event()
        result = await tools.execute(ToolExecutionInput(
            "s", "web_search", {"queries": ["one", "two"]}, signal=signal
        ))
        assert not result.is_error
        assert result.value["sources"] == [
            {"url": "https://one.test"}, {"url": "https://two.test"}
        ]
        assert result.value["truncated"] is True
        assert len(web.search_calls) == 2
        assert web.search_calls[0][1] is web.search_calls[1][1]
        fetched = await tools.execute(ToolExecutionInput(
            "f", "web_fetch", {"url": "https://a.test"}, signal=signal
        ))
        assert not fetched.is_error and fetched.value["statusCode"] == 404
        assert web.fetch_calls[0] == ({"url": "https://a.test"}, signal)
        assert fetched.meta == {"url": "https://a.test", "statusCode": 404, "truncated": False}
    finally:
        await fiber.dispose()
    assert tools.get_tool("web_search") is None and tools.get_tool("web_fetch") is None
    assert prompt.sections == {}


class LegacySearch(WebSearchProvider):
    async def search(self, query, max_results=10, timeout_ms=60000):
        return [{"url": "https://legacy.test", "title": query}]


class LegacyFetch(WebFetchProvider):
    async def fetch(self, url, timeout_ms=30000):
        return {"url": url, "status": 200, "content": "legacy body"}


class SignalAwareLegacyWeb(WebService):
    def __init__(self):
        WebService.__init__(self)
        self.search_signals = []
        self.fetch_signal = None

    async def search(self, query, max_results=10, timeout_ms=60000, signal=None):
        self.search_signals.append(signal)
        return [{"url": "https://signal.test", "title": query}]

    async def fetch(self, url, timeout_ms=30000, signal=None):
        self.fetch_signal = signal
        return {"url": url, "status": 200, "content": "signal body"}


class FailingBatchWeb:
    def __init__(self):
        self.started = asyncio.Event()
        self.sibling_settled = False

    async def search(self, request, signal):
        if request["query"] == "first":
            await self.started.wait()
            raise RuntimeError("first search failed")
        self.started.set()
        while not signal.is_set():
            await asyncio.sleep(0)
        self.sibling_settled = True
        raise RuntimeError("search aborted")

    async def fetch(self, request, signal):
        raise AssertionError("unused")


class WaitingBatchWeb:
    def __init__(self):
        self.started = 0
        self.settled = 0

    async def search(self, request, signal):
        self.started += 1
        await signal.wait()
        self.settled += 1
        raise RuntimeError("caller aborted")

    async def fetch(self, request, signal):
        raise AssertionError("unused")


@pytest.mark.asyncio
async def test_multi_query_failure_aborts_and_waits_for_siblings():
    web = FailingBatchWeb()
    ctx, tools, _prompt, fiber = await mount(web)
    try:
        result = await tools.execute(ToolExecutionInput(
            "batch", "web_search", {"queries": ["first", "second"]}, signal=asyncio.Event()
        ))
        assert result.is_error
        assert "first search failed" in content_text(result)
        assert web.sibling_settled is True
    finally:
        await fiber.dispose()


@pytest.mark.asyncio
async def test_multi_query_caller_abort_wakes_waiting_providers_and_settles_all():
    web = WaitingBatchWeb()
    _ctx, tools, _prompt, fiber = await mount(web)
    caller = asyncio.Event()
    try:
        task = asyncio.ensure_future(tools.execute(ToolExecutionInput(
            "batch-abort", "web_search", {"queries": ["one", "two"]}, signal=caller
        )))
        while web.started < 2:
            await asyncio.sleep(0)
        caller.set()
        result = await asyncio.wait_for(task, 1.0)
        assert result.is_error
        assert web.settled == 2
    finally:
        await fiber.dispose()


@pytest.mark.asyncio
async def test_enablement_controls_tools_and_prompt_guidance():
    ctx, tools, prompt, fiber = await mount(CanonicalWeb(), {"search": True, "fetch": False})
    try:
        assert tools.get_tool("web_search") is not None
        assert tools.get_tool("web_fetch") is None
        assert set(prompt.sections) == {"tool:web_search"}
        assert "returned source snippets" in prompt.sections["tool:web_search"]["text"]
        assert "web_fetch" not in prompt.sections["tool:web_search"]["text"]
    finally:
        await fiber.dispose()


@pytest.mark.asyncio
async def test_legacy_web_service_carrier_is_normalized_to_one_canonical_surface():
    web = WebService()
    web.register_search_provider("legacy", LegacySearch())
    web.register_fetch_provider("legacy", LegacyFetch())
    ctx, tools, _prompt, fiber = await mount(web)
    try:
        search = await tools.execute(ToolExecutionInput(
            "s", "web_search", {"queries": ["query"]}, signal=asyncio.Event()
        ))
        assert search.value == {"sources": [{"url": "https://legacy.test", "title": "query"}],
                                "truncated": False}
        fetch = await tools.execute(ToolExecutionInput(
            "f", "web_fetch", {"url": "https://legacy.test"}, signal=asyncio.Event()
        ))
        assert fetch.value == {"url": "https://legacy.test", "statusCode": 200,
                               "body": {"kind": "text", "content": "legacy body"}, "truncated": False}
    finally:
        await fiber.dispose()


@pytest.mark.asyncio
async def test_signal_capable_legacy_methods_receive_the_execution_signal():
    web = SignalAwareLegacyWeb()
    web.register_search_provider("active", LegacySearch())
    web.register_fetch_provider("active", LegacyFetch())
    _ctx, tools, _prompt, fiber = await mount(web)
    signal = asyncio.Event()
    try:
        await tools.execute(ToolExecutionInput(
            "s", "web_search", {"queries": ["one", "two"]}, signal=signal
        ))
        await tools.execute(ToolExecutionInput(
            "f", "web_fetch", {"url": "https://signal.test"}, signal=signal
        ))
        assert len(web.search_signals) == 2
        assert web.search_signals[0] is web.search_signals[1]
        assert web.search_signals[0] is not signal
        assert web.search_signals[0].caller is signal
        assert web.fetch_signal is signal
    finally:
        await fiber.dispose()


@pytest.mark.asyncio
async def test_no_provider_is_a_structured_web_error_and_tools_stay_visible():
    ctx, tools, _prompt, fiber = await mount(WebService())
    try:
        assert tools.get_tool("web_search") is not None
        result = await tools.execute(ToolExecutionInput(
            "none", "web_search", {"queries": ["q"]}, signal=asyncio.Event()
        ))
        assert result.is_error
        assert result.error["info"]["code"] == "WEB_PROVIDER_UNAVAILABLE"
    finally:
        await fiber.dispose()


def test_config_validation_is_strict():
    with pytest.raises(ValueError, match="searchMaxResults"):
        ToolWebPlugin({"searchMaxResults": 0})
    with pytest.raises(ValueError, match="searchMaxQueries"):
        ToolWebPlugin({"searchMaxQueries": 1.5})
    with pytest.raises(ValueError, match="fetchMaxOutputChars"):
        ToolWebPlugin({"fetchMaxOutputChars": -1})


def test_plugin_uses_pinned_namespace_name():
    assert ToolWebPlugin.name == "tool-web"
