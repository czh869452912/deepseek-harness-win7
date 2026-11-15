"""rc.1 whole-log turn outline; draft updates preserve the served array identity."""
import re

from dsh.cordis.plugin import Plugin


_SPACE = r"\u0009-\u000d\u0020\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff"
_WHITESPACE = re.compile("[" + _SPACE + "]+")
_TRAILING_SPACE = re.compile("[" + _SPACE + "]+$")
_EDGE_SPACE = re.compile("^[" + _SPACE + "]+|[" + _SPACE + "]+$")


def _length(text):
    return len(text.encode("utf-16-le", "surrogatepass")) // 2


def _slice(text, end):
    return text.encode("utf-16-le", "surrogatepass")[:end * 2].decode("utf-16-le", "surrogatepass")


def preview(content, limit):
    text, unread = "", False
    for block in content:
        if block["type"] != "text":
            continue
        if _length(text) >= limit * 2:
            unread = True
            break
        clipped = _length(block["text"]) > limit * 2
        chunk = _slice(block["text"], limit * 2) if clipped else block["text"]
        text += chunk if text == "" else " " + chunk
        if clipped:
            unread = True
            break
    normalized = _EDGE_SPACE.sub("", _WHITESPACE.sub(" ", text))
    if _length(normalized) > limit - 1:
        return _TRAILING_SPACE.sub("", _slice(normalized, limit - 1)) + "…"
    return normalized + "…" if unread else normalized


def _entries(value):
    if not isinstance(value, list):
        raise ValueError("turn outline entries must be an array")
    previous = -1
    parsed = []
    for entry in value:
        if not isinstance(entry, dict) or set(entry) != {"turn", "seq", "prompt", "response"}:
            raise ValueError("invalid turn outline entry")
        for name in ("turn", "seq"):
            number = entry[name]
            if type(number) not in (int, float) or not 0 <= number <= 9007199254740991 or int(number) != number:
                raise ValueError("turn outline %s must be a nonnegative integer" % name)
        if entry["turn"] <= previous:
            raise ValueError("turn outline entries must be strictly increasing by turn")
        previous = entry["turn"]
        for name, limit in (("prompt", 50), ("response", 120)):
            if not isinstance(entry[name], str) or _length(entry[name]) > limit:
                raise ValueError("invalid turn outline %s" % name)
        parsed.append(dict(entry))
    return parsed


def _state(value):
    if not isinstance(value, dict) or set(value) != {"turns", "draft"}:
        raise ValueError("invalid turn outline state")
    if not isinstance(value["draft"], str) or _length(value["draft"]) > 120:
        raise ValueError("invalid turn outline draft")
    return dict(turns=_entries(value["turns"]), draft=value["draft"])


EMPTY_OUTLINE = dict(turns=[], draft="")


def apply_outline(state, event):
    kind, data = event["type"], event["data"]
    turns, draft = state["turns"], state["draft"]
    last = turns[-1] if turns else None
    if kind == "turn/start":
        if last is not None and data["turn"] <= last["turn"]:
            return state
        return dict(turns=turns + [dict(turn=data["turn"], seq=event["seq"], prompt="", response="")], draft="")
    if kind == "user/message":
        if data["source"]["kind"] != "user" or last is None or last["prompt"] != "":
            return state
        prompt = preview(data["content"], 50)
        if prompt == "":
            return state
        return dict(turns=turns[:-1] + [dict(last, prompt=prompt)], draft=draft)
    if kind == "assistant/message":
        next_draft = preview(data["message"]["content"], 120)
        if next_draft == "" or next_draft == draft:
            return state
        return dict(turns=turns, draft=next_draft)
    if kind == "turn/end":
        if draft == "":
            return state
        if last is None or last["response"] == draft:
            return dict(turns=turns, draft="")
        return dict(turns=turns[:-1] + [dict(last, response=draft)], draft="")
    return state


TURN_OUTLINE_DEFINITION = dict(
    key="turnOutline", stateVersion=2, stateSchema=_state,
    init=lambda *_: EMPTY_OUTLINE, apply=apply_outline,
    wire=dict(viewSchema=_entries, view=lambda state: state["turns"],summary=False),
)


class SessionTurnOutlinePlugin(Plugin):
    id = "session-turn-outline"
    inject = ["sessionProjections"]

    async def apply(self, ctx):
        await ctx.get("sessionProjections").register(TURN_OUTLINE_DEFINITION)
