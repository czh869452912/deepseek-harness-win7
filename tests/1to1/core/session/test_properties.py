"""
1:1 Test Parity Suite for @deepseek-ai/dsh-session properties.
Matching packages/core/session/tests/properties.spec.ts.
Compatible with Python 3.8.10 and Windows 7 SP1.
"""

import copy
import random
from typing import Any, Dict, List, Optional
import pytest

from dsh.core.session import Session, SessionId
from dsh.llm.message import create_message, create_tool_result_message, create_user_message


def random_text_content(rng: random.Random) -> List[Dict[str, Any]]:
    count = rng.randint(0, 3)
    return [{"type": "text", "text": f"txt_{rng.randint(0, 9999)}"} for _ in range(count)]


def random_message_event(rng: random.Random) -> Dict[str, Any]:
    choice = rng.randint(0, 3)
    content = random_text_content(rng)
    if choice == 0:
        return {
            "type": "user/message",
            "data": create_user_message({
                "content": content,
                "source": {"kind": "user"},
            }),
            "intent": {"surfaceOp": "append"},
        }
    elif choice == 1:
        return {
            "type": "assistant/message",
            "data": {
                "turn": 1,
                "step": 1,
                "message": create_message({
                    "role": "assistant",
                    "content": content,
                    "source": {"kind": "model", "provider": "mock", "model": "mock"},
                }),
            },
            "intent": {"surfaceOp": "append"},
        }
    elif choice == 2:
        return {
            "type": "assistant/message",
            "data": {
                "turn": 1,
                "step": 1,
                "message": create_message({
                    "role": "assistant",
                    "content": content,
                    "source": {"kind": "model", "provider": "mock", "model": "mock"},
                }),
                "usage": {"inputTokens": 1, "outputTokens": 1},
            },
            "intent": {"surfaceOp": "append"},
        }
    else:
        call_id = f"call_{rng.randint(1, 999)}"
        return {
            "type": "tool/result",
            "data": {
                "turn": 1,
                "step": 1,
                "message": create_tool_result_message({
                    "callId": call_id,
                    "content": content,
                    "isError": rng.choice([True, False]),
                }),
            },
            "intent": {"surfaceOp": "append"},
        }


def random_non_message_event(rng: random.Random) -> Dict[str, Any]:
    choice = rng.randint(0, 4)
    if choice == 0:
        return {"type": "turn/start", "data": {"turn": 1}}
    elif choice == 1:
        return {"type": "turn/end", "data": {"turn": 1, "reason": {"kind": "completed"}}}
    elif choice == 2:
        return {"type": "step/start", "data": {"turn": 1, "step": 1}}
    elif choice == 3:
        return {"type": "step/end", "data": {"turn": 1, "step": 1}}
    else:
        return {
            "type": "assistant/chunk",
            "data": {"turn": 1, "step": 1, "chunk": {"type": "text-delta", "index": 0, "text": f"chunk_{rng.randint(0, 999)}"}},
        }


def random_log(rng: random.Random, max_length: int = 25) -> List[Dict[str, Any]]:
    length = rng.randint(0, max_length)
    events: List[Dict[str, Any]] = []
    for _ in range(length):
        if rng.random() < 0.5:
            events.append(random_message_event(rng))
        else:
            events.append(random_non_message_event(rng))
    return events


counter = 0


def build_session(events: List[Dict[str, Any]]) -> Session:
    global counter
    counter += 1
    session = Session.create(SessionId(f"prop-{counter}"))
    for e in events:
        intent = e.get("intent")
        if intent is not None:
            session.append(e["type"], e["data"], **intent)
        else:
            session.append(e["type"], e["data"])
    return session


class TestSessionProperties:
    def test_derive_messages_is_deterministic(self):
        rng = random.Random(42)
        for _ in range(30):
            events = random_log(rng)
            session = build_session(events)
            assert session.derive_messages() == session.derive_messages()

    def test_seq_is_strictly_monotonic_and_zero_based_contiguous(self):
        rng = random.Random(1337)
        for _ in range(30):
            events = random_log(rng)
            session = build_session(events)
            for i, ev in enumerate(session.events):
                assert ev["seq"] == i
            assert session.seq == len(events)

    def test_replay_from_seed_reproduces_derivation_identically(self):
        rng = random.Random(2026)
        global counter
        for _ in range(30):
            events = random_log(rng)
            original = build_session(events)
            counter += 1
            replayed = Session.create(SessionId(f"replay-{counter}"), list(original.events))
            assert replayed.derive_messages() == original.derive_messages()
            assert replayed.events[: original.seq] == original.events
            assert replayed.seq == original.seq + 1

    def test_replaying_a_log_that_already_ends_in_end_seed_adds_no_further_marker(self):
        rng = random.Random(999)
        global counter
        for _ in range(30):
            events = random_log(rng)
            original = build_session(events)
            counter += 1
            once = Session.create(SessionId(f"idem-a-{counter}"), list(original.events))
            counter += 1
            twice = Session.create(SessionId(f"idem-b-{counter}"), list(once.events))
            assert twice.events == once.events

    def test_non_message_events_never_affect_derived_history(self):
        rng = random.Random(777)
        for _ in range(30):
            msg_count = rng.randint(0, 12)
            noise_count = rng.randint(0, 12)
            messages = [random_message_event(rng) for _ in range(msg_count)]
            noise = [random_non_message_event(rng) for _ in range(noise_count)]

            clean = build_session(messages).derive_messages()

            interleaved: List[Dict[str, Any]] = []
            mi = 0
            ni = 0
            while mi < len(messages) or ni < len(noise):
                take_noise = ni < len(noise) and (mi >= len(messages) or rng.choice([True, False]))
                if take_noise:
                    interleaved.append(noise[ni])
                    ni += 1
                else:
                    interleaved.append(messages[mi])
                    mi += 1

            with_noise = build_session(interleaved).derive_messages()
            assert with_noise == clean

    def test_every_derived_message_has_a_known_role(self):
        rng = random.Random(888)
        for _ in range(30):
            events = random_log(rng)
            session = build_session(events)
            messages = session.derive_messages()
            before = copy.deepcopy(session.events)
            for m in messages:
                assert m["role"] in ("user", "assistant", "system")
            assert session.events == before
