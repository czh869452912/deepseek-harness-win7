"""User questions capability seam (``ctx.userQuestions``)."""

from typing import Any, Callable, Dict, Optional

from dsh.cordis.plugin import Plugin
from dsh.cordis.service import Service
from dsh.llm.error import HarnessError


class UserQuestionError(HarnessError):
    """Stable error taxonomy for user-questions failures."""

    def __init__(self, message: str, code: str, cause: Optional[BaseException] = None):
        super().__init__(message, code)
        self.name = "UserQuestionError"
        self.cause = cause
        if cause is not None:
            self.__cause__ = cause


class UserQuestionProvider:
    """UI-side provider interface for user questions."""

    async def ask(self, request: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError


class UserQuestionService(Service):
    """`ctx.userQuestions`: one active UI provider plus an `ask()` API."""

    def __init__(self, ctx: Any):
        self.ctx = ctx
        self.name = "userQuestions"
        self.provider: Optional[UserQuestionProvider] = None
        ctx.provide(self.name, self)

    def registerProvider(self, provider: Any) -> Callable[[], None]:
        def setup() -> Callable[[], None]:
            if self.provider is not None:
                raise UserQuestionError(
                    "a user-questions provider is already registered",
                    "DUPLICATE_PROVIDER",
                )
            self.provider = provider

            def unregister() -> None:
                if self.provider is provider:
                    self.provider = None

            return unregister

        dispose = self.ctx.effect(setup, label="userInteraction.registerProvider()")

        def unregister_provider() -> None:
            dispose()

        return unregister_provider

    def register_provider(self, provider: Any) -> Callable[[], None]:
        return self.registerProvider(provider)

    async def ask(self, request: Dict[str, Any]) -> Dict[str, Any]:
        signal = request.get("signal")
        if signal is not None and getattr(signal, "aborted", False):
            raise UserQuestionError("ask_user_question was aborted before the user answered", "ASK_ABORTED")

        questions = request.get("questions", [])
        if not questions or len(questions) == 0:
            raise UserQuestionError("ask_user_question requires at least one question", "EMPTY_QUESTIONS")

        agent = request.get("agent")
        if agent is not None:
            agents_svc = self.ctx.get("agents") if self.ctx else None
            get_agent = getattr(agents_svc, "get", None)
            get_roots = getattr(agents_svc, "roots", None)
            if not callable(get_agent) or not callable(get_roots):
                raise UserQuestionError(
                    "human interaction requires the exact live calling agent when an agent is supplied",
                    "CALLER_NOT_LIVE",
                )
            agent_id = getattr(agent, "id", None)
            if get_agent(agent_id) is not agent:
                raise UserQuestionError(
                    "human interaction requires the exact live calling agent when an agent is supplied",
                    "CALLER_NOT_LIVE",
                )
            roots = get_roots()
            try:
                is_root = any(root is agent for root in roots)
            except TypeError:
                raise UserQuestionError(
                    "human interaction requires the exact live calling agent when an agent is supplied",
                    "CALLER_NOT_LIVE",
                )
            if not is_root:
                raise UserQuestionError(
                    "human interaction is unavailable while the calling agent is owned by another live agent; "
                    "include the unresolved question or decision in the child agent's final result",
                    "DELEGATED_CALLER",
                )

        for question in questions:
            intent = question.get("intent")
            if intent is not None:
                options = question.get("options") or []
                approve_label = intent.get("approve")
                if not any(opt.get("label") == approve_label for opt in options if isinstance(opt, dict)):
                    raise UserQuestionError(
                        f"question {question.get('id')} declares intent {intent.get('kind')} whose approve label "
                        f"names none of its options",
                        "BAD_INTENT",
                    )
                if question.get("detail") is None:
                    raise UserQuestionError(
                        f"question {question.get('id')} declares intent {intent.get('kind')} without the detail it reviews",
                        "BAD_INTENT",
                    )

        if self.provider is None:
            raise UserQuestionError("no user-questions provider is registered", "NO_PROVIDER")

        res = self.provider.ask(request)
        if hasattr(res, "__await__"):
            res = await res
        return res


class UserQuestionsPlugin(Plugin):
    """
    Plugin `@deepseek-ai/dsh-user-questions`: Mounts `ctx.userQuestions` service.
    """

    id = "user-questions"
    name = "@deepseek-ai/dsh-user-questions"

    def apply(self, ctx: Any) -> None:
        UserQuestionService(ctx)
