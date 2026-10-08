"""Shared provider schema exported by the pinned LLM retry-policy module."""
from dsh.cordis.schema import Schema as z
from dsh.llm.retry_policy import DEFAULT_CODES, MAX_TIMER_DELAY_MS


_backoff = z.object(dict(
    initialDelayMs=z.number().max(MAX_TIMER_DELAY_MS).default(500),
    maxDelayMs=z.number().max(MAX_TIMER_DELAY_MS).default(10000),
    jitterRatio=z.number().min(0).max(1).default(.1)))

# Keep these nodes shared across provider Config exports and both union arms;
# the browser receives their identity in the flat Schemastery reference table.
RetryPolicySchema = z.union([
    z.object(dict(mode=z.const_('normal').required(),
        maxRetries=z.number().step(1).min(0).max(9007199254740991).default(5),
        retryableCodes=z.array(z.string()).default(DEFAULT_CODES), backoff=_backoff)),
    z.object(dict(mode=z.const_('always').required(), backoff=_backoff)),
])
