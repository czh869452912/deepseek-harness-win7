import pytest
import asyncio

from dsh.cordis.context import Context
from dsh.interaction.user_questions import (
    UserQuestionError,
    UserQuestionService,
    UserQuestionsPlugin,
)
from dsh.llm.error import HarnessError


class RecordingProvider:
    def __init__(self, answer="approved"):
        self.answer = answer
        self.seen = []

    async def ask(self, request):
        self.seen.append(request)
        question_id = request["questions"][0]["id"] if request["questions"] else "missing"
        return {"answers": [{"id": question_id, "selected": [self.answer]}]}


class Agent:
    def __init__(self, agent_id):
        self.id = agent_id


class AgentRegistry:
    def __init__(self, live, roots):
        self.live = live
        self._roots = roots

    def get(self, agent_id):
        return self.live.get(agent_id)

    def roots(self):
        return list(self._roots)


class IncompleteAgentRegistry:
    def __init__(self, live):
        self.live = live

    def get(self, agent_id):
        return self.live.get(agent_id)

    def roots(self):
        return None


class EqualProvider(RecordingProvider):
    def __eq__(self, other):
        return isinstance(other, EqualProvider)


class FalseySignal:
    aborted = True

    def __bool__(self):
        return False


class DirectContext:
    def __init__(self, services=None):
        self.services = services or {}

    def get(self, name):
        return self.services.get(name)

    def provide(self, name, value):
        self.services[name] = value
        return lambda: self.services.pop(name, None)

    def effect(self, setup, label=""):
        teardown = setup()
        disposed = False

        def dispose():
            nonlocal disposed
            if disposed:
                return
            disposed = True
            teardown()

        return dispose


def service_with_provider(ctx=None, provider=None):
    context = ctx or Context()
    service = UserQuestionService(context)
    active_provider = provider or RecordingProvider()
    service.registerProvider(active_provider)
    return service, active_provider


@pytest.mark.asyncio
async def test_delegates_the_original_request_to_the_registered_provider():
    service, provider = service_with_provider(provider=RecordingProvider("yes"))
    request = {"questions": [{"id": "confirm", "question": "Proceed?"}]}

    result = await service.ask(request)

    assert result == {"answers": [{"id": "confirm", "selected": ["yes"]}]}
    assert provider.seen == [request]
    assert provider.seen[0] is request


@pytest.mark.asyncio
async def test_rejects_when_no_provider_is_registered():
    service = UserQuestionService(Context())

    with pytest.raises(UserQuestionError) as caught:
        await service.ask({"questions": [{"id": "confirm", "question": "Proceed?"}]})

    assert caught.value.code == "NO_PROVIDER"
    assert caught.value.name == "UserQuestionError"


def test_user_question_error_preserves_harness_error_taxonomy_and_cause():
    cause = ValueError("root cause")

    error = UserQuestionError("question failed", "QUESTION_FAILED", cause=cause)

    assert isinstance(error, HarnessError)
    assert error.name == "UserQuestionError"
    assert error.code == "QUESTION_FAILED"
    assert error.message == "question failed"
    assert error.cause is cause
    assert error.__cause__ is cause


@pytest.mark.asyncio
async def test_provider_disposer_is_identity_based_and_idempotent():
    service = UserQuestionService(Context())
    first = EqualProvider("first")
    second = EqualProvider("second")
    dispose_first = service.registerProvider(first)

    dispose_first()
    await asyncio.sleep(0)
    service.registerProvider(second)
    dispose_first()

    result = await service.ask({"questions": [{"id": "confirm", "question": "Proceed?"}]})
    assert result["answers"][0]["selected"] == ["second"]


def test_duplicate_provider_is_rejected_without_replacing_the_active_provider():
    service = UserQuestionService(Context())
    first = RecordingProvider("first")
    service.registerProvider(first)

    with pytest.raises(UserQuestionError) as caught:
        service.registerProvider(RecordingProvider("second"))

    assert caught.value.code == "DUPLICATE_PROVIDER"
    assert service.provider is first


@pytest.mark.asyncio
async def test_aborted_signal_fails_before_reaching_provider_even_when_falsey():
    service, provider = service_with_provider()

    with pytest.raises(UserQuestionError) as caught:
        await service.ask({
            "questions": [{"id": "confirm", "question": "Proceed?"}],
            "signal": FalseySignal(),
        })

    assert caught.value.code == "ASK_ABORTED"
    assert provider.seen == []


@pytest.mark.asyncio
async def test_empty_questions_fail_before_reaching_provider():
    service, provider = service_with_provider()

    with pytest.raises(UserQuestionError) as caught:
        await service.ask({"questions": []})

    assert caught.value.code == "EMPTY_QUESTIONS"
    assert provider.seen == []


@pytest.mark.asyncio
@pytest.mark.parametrize("agents", [None, object()])
async def test_agent_requires_a_complete_live_registry(agents):
    ctx = DirectContext({"agents": agents} if agents is not None else {})
    service, provider = service_with_provider(ctx)

    with pytest.raises(UserQuestionError) as caught:
        await service.ask({
            "questions": [{"id": "confirm", "question": "Proceed?"}],
            "agent": Agent("unattested"),
        })

    assert caught.value.code == "CALLER_NOT_LIVE"
    assert provider.seen == []


@pytest.mark.asyncio
async def test_agent_registry_with_no_root_collection_is_not_live_attestation():
    agent = Agent("unattested")
    ctx = DirectContext({"agents": IncompleteAgentRegistry({agent.id: agent})})
    service, provider = service_with_provider(ctx)

    with pytest.raises(UserQuestionError) as caught:
        await service.ask({
            "questions": [{"id": "confirm", "question": "Proceed?"}],
            "agent": agent,
        })

    assert caught.value.code == "CALLER_NOT_LIVE"
    assert provider.seen == []


@pytest.mark.asyncio
async def test_stale_equal_agent_with_live_id_is_rejected_by_identity():
    class EqualAgent(Agent):
        def __eq__(self, other):
            return isinstance(other, EqualAgent) and self.id == other.id

    live = EqualAgent("same-id")
    stale = EqualAgent("same-id")
    ctx = DirectContext({"agents": AgentRegistry({live.id: live}, [live])})
    service, provider = service_with_provider(ctx)

    with pytest.raises(UserQuestionError) as caught:
        await service.ask({
            "questions": [{"id": "confirm", "question": "Proceed?"}],
            "agent": stale,
        })

    assert caught.value.code == "CALLER_NOT_LIVE"
    assert provider.seen == []


@pytest.mark.asyncio
async def test_live_equal_child_is_rejected_by_root_identity():
    class AlwaysEqualAgent(Agent):
        def __eq__(self, other):
            return isinstance(other, AlwaysEqualAgent)

    root = AlwaysEqualAgent("root")
    child = AlwaysEqualAgent("child")
    ctx = DirectContext({"agents": AgentRegistry({child.id: child}, [root])})
    service, provider = service_with_provider(ctx)

    with pytest.raises(UserQuestionError) as caught:
        await service.ask({
            "questions": [{"id": "confirm", "question": "Proceed?"}],
            "agent": child,
        })

    assert caught.value.code == "DELEGATED_CALLER"
    assert provider.seen == []


@pytest.mark.asyncio
async def test_live_runtime_root_reaches_provider_regardless_of_session_lineage():
    agent = Agent("resumed-root")
    ctx = DirectContext({"agents": AgentRegistry({agent.id: agent}, [agent])})
    service, provider = service_with_provider(ctx, RecordingProvider("yes"))

    result = await service.ask({
        "questions": [{"id": "confirm", "question": "Proceed?"}],
        "agent": agent,
    })

    assert result["answers"][0]["selected"] == ["yes"]
    assert len(provider.seen) == 1


@pytest.mark.asyncio
async def test_none_options_are_an_empty_list_for_intent_validation():
    service, provider = service_with_provider()

    with pytest.raises(UserQuestionError) as caught:
        await service.ask({"questions": [{
            "id": "plan-review",
            "question": "Approve?",
            "detail": "# Plan",
            "options": None,
            "intent": {"kind": "plan-review", "approve": "Ship it"},
        }]})

    assert caught.value.code == "BAD_INTENT"
    assert provider.seen == []


@pytest.mark.asyncio
async def test_intent_requires_detail_before_reaching_provider():
    service, provider = service_with_provider()

    with pytest.raises(UserQuestionError) as caught:
        await service.ask({"questions": [{
            "id": "plan-review",
            "question": "Approve?",
            "options": [{"label": "Approve"}, {"label": "Keep planning"}],
            "intent": {"kind": "plan-review", "approve": "Approve"},
        }]})

    assert caught.value.code == "BAD_INTENT"
    assert provider.seen == []


@pytest.mark.asyncio
async def test_valid_intent_is_passed_through_unchanged():
    service, provider = service_with_provider(provider=RecordingProvider("Approve"))
    intent = {"kind": "plan-review", "approve": "Approve"}
    request = {"questions": [
        {"id": "plain", "question": "Proceed?"},
        {
            "id": "plan-review",
            "question": "Approve?",
            "detail": "# Plan",
            "options": [{"label": "Approve"}, {"label": "Keep planning"}],
            "intent": intent,
        },
    ]}

    await service.ask(request)

    assert provider.seen[0]["questions"][1]["intent"] is intent


@pytest.mark.asyncio
async def test_plugin_service_is_fiber_owned_and_removed_on_unload():
    ctx = Context()
    fiber = await ctx.registry.plugin(UserQuestionsPlugin, parent_ctx=ctx)
    service = fiber.ctx.get("userQuestions")

    assert isinstance(service, UserQuestionService)
    assert "userQuestions" not in ctx._services
    assert fiber is not None
    assert fiber.store["userQuestions"].value is service

    assert await ctx.registry.unload_plugin("user-questions") is True
    assert ctx.get("userQuestions") is None
    assert "userQuestions" not in ctx._services
    assert "userQuestions" not in ctx.reflect.store
    assert not hasattr(ctx, "userQuestions")
