"""Observe canonical Python meter and projection folds over shared session recipes."""
import asyncio
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from dsh.cordis.context import Context
from dsh.core.session import SessionPlugin
from dsh.llm.message import create_user_message, create_assistant_message
from dsh.llm.token_meter import TokenMeterPlugin, estimate_content, estimate_header
from dsh.session.projections import SessionProjectionsPlugin


class Pricing:
    def priceImages(self, refs):
        return [dict(visualTokens=ref["width"] + index, text="Image handle") for index, ref in enumerate(refs)]


class Llm:
    def imageRequestPricing(self, provider, model):
        return Pricing() if model == "vision" else None


async def observe():
    cases = json.loads((ROOT / "scripts/oracles/token-meter-cases.json").read_text(encoding="utf-8"))
    rows = []
    for spec in cases:
        ctx = Context()
        try:
            await ctx.plugin(SessionPlugin)
            await ctx.plugin(SessionProjectionsPlugin)
            ctx.set_service("llm", Llm())
            await ctx.plugin(TokenMeterPlugin)
            meter, registry = ctx.get("tokenMeter"), ctx.get("sessionProjections")
            session, output, step = ctx.get("sessions").create(), [], 0
            def user(text, **options):
                return session.append("user/message", create_user_message(dict(content=text)),
                                      surface_op=options.pop("surface_op", "append"), **options)
            for action in spec["actions"]:
                op = action["op"]
                header = action.get("header", dict(config=dict(provider="mock", model="mock"), system="system"))
                if op == "user":
                    user(action["text"])
                elif op == "header":
                    session.append("request/header", dict(header=header, reason="initial"))
                elif op in ("call", "input-call"):
                    step += 1
                    session.append("step/start", dict(turn=1, step=step))
                    if op == "input-call":
                        user(action["input"])
                    if header is not None:
                        session.append("request/header", dict(header=header, reason="initial"))
                    text, seqs = action.get("text", "answer"), []
                    if action.get("provenance") == "exact":
                        provider_text = action.get("providerText", text)
                        chunks = [dict(type="block-start", index=0, blockType="text"),
                                  dict(type="text-delta", index=0, text=provider_text),
                                  dict(type="block-end", index=0, block=dict(type="text", text=provider_text)),
                                  dict(type="finish", reason=dict(kind="stop"))]
                        for chunk in chunks:
                            seqs.append(session.append("assistant/chunk", dict(turn=1, step=step, chunk=chunk))["seq"])
                    data = dict(turn=1, step=step, message=create_assistant_message(dict(content=text)))
                    if "usage" in action:
                        data["usage"] = action["usage"]
                    options = dict(source_event_seqs=seqs) if "provenance" in action else {}
                    session.append("assistant/message", data, surface_op="append", **options)
                    session.append("step/end", dict(turn=1, step=step))
                elif op == "replace":
                    nodes = meter.measure(session)["nodes"]
                    positions = [row["seq"] for row in nodes]
                    selected = nodes[positions.index(action["start"]):positions.index(action["end"]) + 1]
                    seqs = [row["seq"] for row in selected]
                    if action.get("metered"):
                        session.append("compaction/prune", dict(shadowedRange=dict(start=action["start"], end=action["end"]),
                                                               shadowedSeqs=seqs, shadowedTokenCount=sum(row["heuristicTokens"] for row in selected)))
                    user(action["text"], surface_op=dict(op="replace", start=action["start"], end=action["end"]), source_event_seqs=seqs)
                elif op == "usage":
                    session.append("assistant/chunk", dict(turn=1, step=1, chunk=dict(type="usage", usage=action["usage"])))
                elif op == "retry":
                    session.append("llm/retry-started", dict(turn=1, step=1))
                elif op == "context":
                    session.append("request/context", {key: action[key] for key in ("contextWindow",) if key in action})
                elif op == "estimate":
                    output.append(dict(content=estimate_content(action["content"]), header=estimate_header(action["header"])))
                elif op == "measure":
                    output.append(dict(measurement=meter.measure(session, action.get("header")),
                                       projection=registry.snapshot(session), checkpoint=registry.checkpoint(session)))
                else:
                    raise ValueError("unknown action")
            rows.append(dict(mode=spec["mode"], output=output))
        finally:
            await ctx.fiber.dispose()
    return rows


if __name__ == "__main__":
    Path(sys.argv[1]).write_text(json.dumps(asyncio.run(observe()), ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
