"""
Tool-independent shell environment plugin: owns the `ctx.shellEnv` registry of
trusted, per-execution `DSH_*` variables consumed by the model-facing shell
tools. Built-in shell facts are owned by the registry itself while plugins can
register additional, enumerable facts with effect-scoped disposal.

1:1 aligned with reference/packages/shell/shell-env/src/index.ts.
Compatible with Python 3.8.10 and Windows 7 SP1.
"""

import re
from typing import Any, Callable, Dict, List, Mapping, Optional

from dsh.cordis.environment import DSH_HOME_ENV, resolve_dsh_home
from dsh.cordis.plugin import Plugin
from dsh.cordis.service import Service

from dsh.subprocess.types import DSH_ENV_PREFIX

DSH_SHELL_KEY = DSH_ENV_PREFIX + "SHELL"
DSH_SESSION_ID_KEY = DSH_ENV_PREFIX + "SESSION_ID"
DSH_SESSION_JSONL_KEY = DSH_ENV_PREFIX + "SESSION_JSONL"

RESERVED_BASH_ENV_KEYS = (DSH_HOME_ENV, DSH_SHELL_KEY, DSH_SESSION_ID_KEY)

BASH_ENV_KEY_SUFFIX = re.compile(r"^[A-Z][A-Z0-9_]*$")

SERVICE_NAME = "shellEnv"

SESSION_PERSISTENCE_CONTRIBUTOR = "session-persistence"

SESSION_JSONL_DESCRIPTION = (
    "Absolute target path of the current session JSONL when the active persistence backend provides one."
)


def _member(value: Any, name: str) -> Any:
    """Read one member of a contributor-shaped value (mapping or attribute)."""
    if isinstance(value, Mapping):
        return value.get(name)
    return getattr(value, name, None)


def _variable_description(variable: Any) -> str:
    """Read one declared variable's description from its declaration."""
    if isinstance(variable, Mapping):
        return variable.get("description", "")
    return getattr(variable, "description", "")


def _declared_variables(contributor: Any) -> List[Any]:
    """Every declared `key -> variable` pair of one contributor, in declaration order."""
    variables: Any = _member(contributor, "variables") or {}
    if isinstance(variables, Mapping):
        return list(variables.items())
    return list(variables)


def execution_agent(execution: Any) -> Any:
    """Read the optional calling agent off one tool execution."""
    return _member(execution, "agent")


def _agent_session_id(agent: Any) -> Optional[str]:
    """Read the calling agent's exact session id, as upstream's `agent.session.header.id`."""
    session = _member(agent, "session")
    header = _member(session, "header")
    session_id = _member(header, "id")
    if session_id is None:
        session_id = _member(session, "id")
    return session_id


class ShellEnvRegistry(Service):
    """
    Registry (`ctx.shellEnv`) for trusted, per-execution `DSH_*` variables.

    Built-in shell facts remain owned by the registry itself while plugins can
    register additional, enumerable facts with effect-scoped disposal.
    """

    def __init__(self, ctx: Any = None, config: Optional[Dict[str, Any]] = None, allow_replace: bool = False):
        self._contributors: Dict[str, Any] = {}
        self._key_owners: Dict[str, str] = {}
        super().__init__(ctx, SERVICE_NAME, allow_replace=allow_replace)
        self.dsh_home = resolve_dsh_home((config or {}).get("dshHome"))

    @property
    def contributors(self) -> Dict[str, Any]:
        """Live contributor map, in registration order."""
        return self._contributors

    def register(self, contributor: Any) -> Callable[[], None]:
        """
        Register one environment contributor.

        Names and keys are unique; built-in keys are reserved. Registration is
        disposed with the calling plugin fiber, and the returned callable is the
        explicit disposer.

        @param contributor: declared key ownership and per-execution resolver.
        @returns: the disposer that unregisters the contribution.
        """
        name = _member(contributor, "name")
        if not isinstance(name, str) or len(name.strip()) == 0:
            raise ValueError("bash env contributor name must be non-empty")
        if name in self._contributors:
            raise ValueError(f'bash env contributor "{name}" is already registered')

        declared = _declared_variables(contributor)
        for key, variable in declared:
            if (
                not isinstance(key, str)
                or not key.startswith(DSH_ENV_PREFIX)
                or not BASH_ENV_KEY_SUFFIX.match(key[len(DSH_ENV_PREFIX):])
            ):
                raise ValueError(f'bash env contributor "{name}" declared invalid key "{key}"')
            if key in RESERVED_BASH_ENV_KEYS:
                raise ValueError(f'bash env contributor "{name}" cannot own reserved key "{key}"')
            description = _variable_description(variable)
            if not isinstance(description, str) or len(description.strip()) == 0:
                raise ValueError(f'bash env contributor "{name}" must describe "{key}"')
            owner = self._key_owners.get(key)
            if owner is not None:
                raise ValueError(
                    f'bash env key "{key}" is already owned by contributor "{owner}"; '
                    f'contributor "{name}" cannot also own it'
                )

        self._contributors[name] = contributor
        for key, _ in declared:
            self._key_owners[key] = name

        def cleanup() -> None:
            self._contributors.pop(name, None)
            for key, _ in declared:
                self._key_owners.pop(key, None)

        return self.ctx.disposable(cleanup, label="bashEnv.register()")

    def collect(self, execution: Any) -> Dict[str, str]:
        """
        Build the trusted `DSH_*` snapshot for one shell tool execution.

        @param execution: the current tool execution.
        @returns: the environment overlay containing built-ins and current contributions.
        """
        values: Dict[str, str] = {
            DSH_HOME_ENV: self.dsh_home,
            DSH_SHELL_KEY: "1",
        }
        agent = execution_agent(execution)
        if agent is not None:
            session_id = _agent_session_id(agent)
            if session_id is not None:
                values[DSH_SESSION_ID_KEY] = session_id

        for contributor in sorted(
            self._contributors.values(),
            key=lambda item: _member(item, "name"),
        ):
            name = _member(contributor, "name")
            variables: Any = _member(contributor, "variables") or {}
            resolver = _member(contributor, "resolve")
            resolved = resolver(execution) if resolver is not None else {}
            for raw_key, value in (resolved or {}).items():
                if raw_key not in variables:
                    raise ValueError(f'bash env contributor "{name}" returned undeclared key "{raw_key}"')
                if not isinstance(value, str):
                    raise ValueError(
                        f'bash env contributor "{name}" returned a non-string value for "{raw_key}"'
                    )
                values[raw_key] = value

        return {key: values[key] for key in sorted(values)}

    def list(self) -> List[Dict[str, str]]:
        """
        Enumerate plugin-contributed variables without executing their resolvers.

        @returns: declarations sorted by environment variable name.
        """
        declared: List[Dict[str, str]] = []
        for contributor in self._contributors.values():
            name = _member(contributor, "name")
            for key, variable in _declared_variables(contributor):
                declared.append({
                    "contributor": name,
                    "description": _variable_description(variable),
                    "key": key,
                })
        declared.sort(key=lambda entry: entry["key"])
        return declared


def session_persistence_contributor(ctx: Any) -> Dict[str, Any]:
    """The shell-agnostic persistence contributor owning `DSH_SESSION_JSONL`."""

    def resolve(execution: Any) -> Dict[str, str]:
        agent = execution_agent(execution)
        if agent is None:
            return {}
        persistence = ctx.get("sessionPersistence") if hasattr(ctx, "get") else None
        if persistence is None or not hasattr(persistence, "locate"):
            return {}
        header = _member(_member(agent, "session"), "header")
        location = persistence.locate(header)
        if location is None:
            return {}
        if _member(location, "kind") != "jsonl":
            return {}
        return {DSH_SESSION_JSONL_KEY: _member(location, "path")}

    return {
        "name": SESSION_PERSISTENCE_CONTRIBUTOR,
        "variables": {
            DSH_SESSION_JSONL_KEY: {"description": SESSION_JSONL_DESCRIPTION},
        },
        "resolve": resolve,
    }


class ShellEnvPlugin(Plugin):
    """
    Plugin `@deepseek-ai/dsh-shell-env`: installs the `ctx.shellEnv` registry
    and the shell-agnostic persistence contributor (`DSH_SESSION_JSONL`).
    """

    id = "shell-env"
    name = "@deepseek-ai/dsh-shell-env"
    inject: List[str] = []

    def apply(self, ctx: Any, config: Optional[Any] = None) -> None:
        registry = ShellEnvRegistry(ctx, self.config)
        registry.register(session_persistence_contributor(ctx))
