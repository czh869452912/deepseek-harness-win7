"""Cold-safe session summaries without creating Agents or publishing Sessions."""
import asyncio
import logging
import os


def _metadata(value):
    if not isinstance(value, dict) or type(value.get("blank")) is not bool:
        raise ValueError("invalid session list metadata")
    stamp = value.get("lastPromptAt")
    if stamp is not None and type(stamp) not in (int, float):
        raise ValueError("invalid last prompt timestamp")
    return {"blank": value["blank"], "lastPromptAt": stamp}


def apply_list_metadata(state, event):
    blank = state["blank"] and event["type"] != "turn/start"
    last = event["time"] if event["type"] == "user/message" and event.get("data", {}).get("source", {}).get("kind") == "user" else state["lastPromptAt"]
    return state if blank == state["blank"] and last == state["lastPromptAt"] else {"blank": blank, "lastPromptAt": last}


class SessionListing:
    def __init__(self, ctx, cold_probe_max_bytes=1024):
        self.ctx, self.cold_probe_max_bytes = ctx, cold_probe_max_bytes
        projections = ctx.get("sessionProjections")
        if projections is not None:
            projections.register({"key": "sessionListMetadata", "stateVersion": 1,
                "stateSchema": _metadata, "init": lambda _: {"blank": True, "lastPromptAt": None},
                "apply": apply_list_metadata,
                "wire": {"viewSchema": _metadata, "view": lambda state: state}})

    def _projection(self, header, live):
        try:
            service = self.ctx.get("sessionProjections" if live is not None else "sessionProjectionCache")
            return service.cached_snapshot(live if live is not None else header) if service is not None else None
        except Exception as error:
            logging.getLogger("session-list").warning("Cannot read projection: %s", error)
            return None

    def _summary(self, header, live, projection):
        metadata = (projection or {}).get("values", {}).get("sessionListMetadata", {})
        agents = self.ctx.get("agents")
        agent = agents.get(header.id) if agents is not None else None
        row = {"sessionId": header.id, "updatedAt": max(header.createdAt, metadata.get("lastPromptAt") or 0),
               "running": live is not None and agent is not None and agent.status == "running",
               "blank": metadata.get("blank", live.seq == 0 if live is not None else False)}
        for attribute, field in (("cwd", "cwd"), ("parentSession", "parentSessionId"), ("origin", "origin")):
            value = getattr(header, attribute, None)
            if value is not None:
                row[field] = value
        if projection and projection.get("values"):
            row["projections"] = projection
        return row

    async def _cold(self, header, persistence):
        projection = self._projection(header, None)
        metadata = (projection or {}).get("values", {}).get("sessionListMetadata", {})
        if metadata.get("blank") is not False and self.cold_probe_max_bytes > 0:
            location = persistence.locate(header)
            try:
                if location is not None and os.stat(location.path).st_size <= self.cold_probe_max_bytes:
                    observed = await persistence.inspect(header.id)
                    cache = self.ctx.get("sessionProjectionCache")
                    if cache is not None:
                        projection = cache.cold_snapshot(observed.meta, observed.events)
                    else:
                        registry = self.ctx.get("sessionProjections")
                        if registry is not None:
                            projection = registry.restore({}, observed.events, 0, observed.meta)["snapshot"]
            except Exception as error:
                logging.getLogger("session-list").warning("Cold session remains visible: %s", error)
        live = self.ctx.get("sessions").get(header.id)
        return self._summary(live.header if live is not None else header, live,
                             self._projection(live.header, live) if live is not None else projection)

    async def list(self):
        sessions, persistence = self.ctx.get("sessions"), self.ctx.get("sessionPersistence")
        live = {session.id: session for session in sessions.list()} if sessions is not None else {}
        result = [self._summary(s.header, s, self._projection(s.header, s)) for s in live.values()]
        if persistence is not None:
            headers = [h for h in await persistence.list() if h.id not in live and h.cwd is not None]
            for offset in range(0, len(headers), 16):
                result.extend(await asyncio.gather(*(self._cold(h, persistence) for h in headers[offset:offset + 16])))
        return sorted(result, key=lambda row: row["updatedAt"], reverse=True)
