"""
Service Definition for the user-questions capability seam (`ctx.userQuestions`).
Aligned 1:1 with official `@deepseek-ai/dsh-user-questions`.
"""

from typing import Any, Callable, Dict, List, Optional, Union
from dsh.cordis.plugin import Plugin


class UserQuestionError(Exception):
    """Stable error taxonomy for user-questions failures."""

    def __init__(self, message: str, code: str):
        super().__init__(message)
        self.message = message
        self.code = code


class UserQuestionProvider:
    """UI-side provider interface for user questions."""

    async def ask(self, request: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError


class UserQuestionService:
    """`ctx.userQuestions`: validation plus the scoped answerer waterfall."""

    def __init__(self, ctx: Any):
        self.ctx = ctx
        self.provider: Optional[Any] = None

    def registerProvider(self, provider: Any) -> Callable[[], None]:
        self.provider = provider

        async def answerer(request: Dict[str, Any], next_fn: Optional[Callable[[], Any]] = None) -> Any:
            if hasattr(provider, "ask"):
                res = provider.ask(request)
            elif callable(provider):
                res = provider(request)
            else:
                raise TypeError("provider must be callable or have an ask() method")
            if hasattr(res, "__await__"):
                res = await res
            return res

        disposer = self.ctx.on("user-questions/request", answerer) if self.ctx else (lambda: None)

        def unregister() -> None:
            if self.provider == provider:
                self.provider = None
            disposer()

        if self.ctx and hasattr(self.ctx, "effect"):
            self.ctx.effect(unregister)
        return unregister

    def register_provider(self, provider: Any) -> Callable[[], None]:
        return self.registerProvider(provider)

    async def ask(self, request: Dict[str, Any]) -> Dict[str, Any]:
        signal = request.get("signal")
        if signal and getattr(signal, "aborted", False):
            raise UserQuestionError("ask_user_question was aborted before the user answered", "ASK_ABORTED")

        questions = request.get("questions", [])
        if not questions or len(questions) == 0:
            raise UserQuestionError("ask_user_question requires at least one question", "EMPTY_QUESTIONS")

        agent = request.get("agent")
        if agent is not None and self.ctx:
            agents_svc = self.ctx.get("agents")
            if agents_svc is not None:
                agent_id = getattr(agent, "id", None)
                if hasattr(agents_svc, "get") and agents_svc.get(agent_id) != agent:
                    raise UserQuestionError(
                        "human interaction requires the exact live calling agent when an agent is supplied",
                        "CALLER_NOT_LIVE",
                    )
                if hasattr(agents_svc, "roots") and callable(agents_svc.roots):
                    roots = agents_svc.roots()
                    if agent not in roots:
                        raise UserQuestionError(
                            "human interaction is unavailable while the calling agent is owned by another live agent; "
                            "include the unresolved question or decision in the child agent's final result",
                            "DELEGATED_CALLER",
                        )

        for question in questions:
            intent = question.get("intent")
            if intent is not None:
                options = question.get("options", [])
                approve_label = intent.get("approve")
                if not any(opt.get("label") == approve_label for opt in options if isinstance(opt, dict)):
                    raise UserQuestionError(
                        f"question {question.get('id')} declares intent {intent.get('kind')} whose approve label "
                        f"{approve_label} names none of its options",
                        "BAD_INTENT",
                    )
                if question.get("detail") is None:
                    raise UserQuestionError(
                        f"question {question.get('id')} declares intent {intent.get('kind')} without the detail it reviews",
                        "BAD_INTENT",
                    )

        async def no_answerer(*args: Any, **kwargs: Any) -> Any:
            raise UserQuestionError("no user-questions answerer accepted the request", "NO_PROVIDER")

        if self.ctx and hasattr(self.ctx, "waterfall"):
            try:
                res = await self.ctx.waterfall("user-questions/request", request, no_answerer)
                return res
            except UserQuestionError:
                raise
            except Exception as e:
                if signal and getattr(signal, "aborted", False):
                    raise UserQuestionError("ask_user_question was aborted before the user answered", "ASK_ABORTED") from e
                raise

        if self.provider is not None:
            res = self.provider.ask(request)
            if hasattr(res, "__await__"):
                res = await res
            return res

        await no_answerer()
        return {}


class UserQuestionsPlugin(Plugin):
    """
    Plugin `@deepseek-ai/dsh-user-questions`: Mounts `ctx.userQuestions` service.
    """

    id = "user-questions"
    name = "@deepseek-ai/dsh-user-questions"

    def apply(self, ctx: Any) -> None:
        svc = UserQuestionService(ctx)
        ctx.set_service("userQuestions", svc)
