"""Read the non-owner caller fixed by trusted Remote invocation state."""
from dsh.core.session.json import UNDEFINED


def field(value, name):
    return value.get(name, UNDEFINED) if isinstance(value, dict) else getattr(value, name, UNDEFINED)


def principal_of(invocation):
    if invocation is None or invocation is UNDEFINED:
        return UNDEFINED
    principal = field(field(invocation, 'peer'), 'principal')
    return UNDEFINED if field(principal, 'kind') == 'owner' else principal


principalOf = principal_of
