"""Strict replay of the pinned upstream goal/change v1 protocol."""
import copy
import re

MAX_SAFE_INTEGER = 9007199254740991


def integer(value, minimum=0):
    if type(value) not in (int, float) or not minimum <= value <= MAX_SAFE_INTEGER or int(value) != value:
        raise ValueError("goal value must be a safe integer >= {}".format(minimum))
    return int(value)


def exact(value, keys):
    if not isinstance(value, dict) or set(value) != set(keys.split()):
        raise ValueError("goal record must have exactly {} fields".format(keys))


def normalized(value):
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValueError("goal text must be non-empty and normalized")


def decode_ref(value):
    exact(value, "id revision")
    if not isinstance(value["id"], str) or not value["id"]:
        raise ValueError("goal id must be non-empty")
    integer(value["revision"], 1)


def decode_snapshot(value):
    if not isinstance(value, dict) or value.get("phase") not in ("active", "paused", "blocked", "complete"):
        raise ValueError("invalid goal phase")
    exact(value, "id revision objective phase maxGoalRounds" + (" blockedReason" if value["phase"] == "blocked" else ""))
    decode_ref({key: value[key] for key in ("id", "revision")})
    normalized(value["objective"])
    integer(value["maxGoalRounds"], 1)
    if value["phase"] == "blocked":
        reason = value["blockedReason"]
        exact(reason, "code message")
        if not isinstance(reason["code"], str) or re.fullmatch(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*", reason["code"]) is None:
            raise ValueError("goal block code must be lower-kebab-case")
        normalized(reason["message"])


def decode_goal_change(value):
    if not isinstance(value, dict) or value.get("kind") != "goal/change":
        return None
    if type(value.get("version")) is not int or value["version"] != 1:
        raise ValueError("unsupported goal change version")
    if value.get("operation") == "clear":
        exact(value, "kind version operation cleared clearedAt")
        decode_ref(value["cleared"])
        integer(value["clearedAt"])
    else:
        exact(value, "kind version operation goal roundsStarted createdAt updatedAt")
        if value["operation"] not in ("create", "edit", "pause", "resume", "complete", "block"):
            raise ValueError("invalid goal operation")
        decode_snapshot(value["goal"])
        for key in ("roundsStarted", "createdAt", "updatedAt"):
            integer(value[key])
        if value["updatedAt"] < value["createdAt"]:
            raise ValueError("goal update precedes creation")
    return copy.deepcopy(value)


def empty_goal_state():
    return {"goal": None, "roundsStarted": 0, "createdAt": None, "updatedAt": None,
            "lastRef": None, "seenGoalIds": set()}


def goal_ref(goal):
    return {"id": goal["id"], "revision": goal["revision"]}


def apply_goal_change(state, change):
    operation, current = change["operation"], state["goal"]
    next_goal = change.get("goal", change.get("cleared"))
    if operation == "create":
        if (next_goal["revision"] != 1 or next_goal["phase"] != "active" or change["roundsStarted"] != 0
                or (current is not None and current["phase"] != "complete") or next_goal["id"] in state["seenGoalIds"]):
            raise ValueError("goal create requires a fresh active revision-one goal with zero rounds")
    else:
        if current is None or next_goal["id"] != current["id"] or next_goal["revision"] != current["revision"] + 1:
            raise ValueError("goal mutation must advance the current goal by one revision")
        if operation == "clear":
            if change["clearedAt"] < state["updatedAt"]:
                raise ValueError("goal clear timestamp precedes update")
        else:
            if (change["createdAt"] != state["createdAt"] or change["updatedAt"] < state["updatedAt"]
                    or change["roundsStarted"] != state["roundsStarted"]):
                raise ValueError("goal mutation must preserve counters and timestamps")
            if operation == "edit":
                if next_goal["phase"] != current["phase"] or next_goal.get("blockedReason") != current.get("blockedReason"):
                    raise ValueError("goal edit cannot change phase or blocked reason")
            else:
                if any(next_goal[key] != current[key] for key in ("objective", "maxGoalRounds")):
                    raise ValueError("goal phase mutation cannot change definition")
                allowed, target = {"pause": (("active",), "paused"), "resume": (("active", "paused", "blocked"), "active"),
                                   "complete": (("active", "paused", "blocked"), "complete"), "block": (("active",), "blocked")}[operation]
                if current["phase"] not in allowed or next_goal["phase"] != target:
                    raise ValueError("invalid goal phase transition")
                if operation == "resume" and state["roundsStarted"] >= next_goal["maxGoalRounds"]:
                    raise ValueError("goal resume has exhausted round budget")
    state["lastRef"] = goal_ref(next_goal)
    if operation == "clear":
        state.update(goal=None, roundsStarted=0, createdAt=None, updatedAt=None)
    else:
        if operation == "create":
            state["seenGoalIds"].add(next_goal["id"])
        state.update({key: copy.deepcopy(change[key]) for key in ("goal", "roundsStarted", "createdAt", "updatedAt")})


def apply_goal_event(state, event):
    if event["type"] == "goal/change":
        change = decode_goal_change(event["data"])
        if change is None:
            raise ValueError("goal change has invalid kind")
        apply_goal_change(state, change)
    elif event["type"] == "user/message":
        source = event["data"].get("source", {})
        if source.get("kind") != "goal":
            return
        integer(source.get("revision"), 1)
        integer(source.get("round"), 1)
        current = state["goal"]
        if (current is None or current["phase"] != "active" or source.get("goalId") != current["id"]
                or source["revision"] != current["revision"] or source["round"] != state["roundsStarted"] + 1
                or source["round"] > current["maxGoalRounds"]):
            raise ValueError("goal message is not the next admitted round of the active goal")
        state["roundsStarted"] = source["round"]


def fold_goal(events):
    state = empty_goal_state()
    for event in events:
        apply_goal_event(state, event)
    return {key: copy.deepcopy(value) for key, value in state.items() if key != "seenGoalIds" and value is not None}


def apply_goal_projection(state, event):
    if event["type"] != "goal/change":
        return state
    try:
        change = decode_goal_change(event["data"])
    except ValueError:
        return state
    if change is None:
        return state
    return None if change["operation"] == "clear" else {key: change[key] for key in ("goal", "roundsStarted", "createdAt", "updatedAt")}


def projection_schema(value):
    if value is not None:
        exact(value, "goal roundsStarted createdAt updatedAt")
        decode_snapshot(value["goal"])
        for key in ("roundsStarted", "createdAt", "updatedAt"):
            integer(value[key])
    return value
