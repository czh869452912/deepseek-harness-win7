import pytest
from dsh.cordis.context import Context
from dsh.core.session import Session
from dsh.session.projections import SessionProjectionRegistry, SessionProjectionsPlugin


def test_session_projection_registry_lifecycle():
    ctx = Context()
    ctx.plugin(SessionProjectionsPlugin)
    
    reg: SessionProjectionRegistry = ctx.get("sessionProjections")
    assert reg is not None

    def sample_init():
        return {"count": 0}

    def sample_apply(state, event):
        evt_type = event.get("type") if isinstance(event, dict) else getattr(event, "type", "")
        if evt_type == "counter/inc":
            return {"count": state["count"] + 1}
        return state

    def sample_view(state):
        return state["count"]

    changes = []
    reg.on_change(lambda sess, key, val, seq: changes.append((key, val, seq)))

    unregister = reg.register(
        key="counter",
        schema={"type": "integer"},
        init=sample_init,
        apply=sample_apply,
        view=sample_view,
    )
    assert reg.has("counter")

    sess = Session("test-session")
    
    # Send event through context
    evt1 = {"type": "counter/inc", "seq": 1, "data": {}}
    sess.events.append(evt1)
    ctx.emit("session/event", sess, evt1)


    assert len(changes) == 1
    assert changes[0] == ("counter", 1, 1)

    snap = reg.snapshot(sess)
    assert snap["values"]["counter"] == 1

    unregister()
    assert not reg.has("counter")
