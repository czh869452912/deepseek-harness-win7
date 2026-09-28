"""Schemastery metadata and defaults for the native provider settings editor."""
from dsh.cordis.schema import Schema as z
from dsh.llm.deepseek_config import DEFAULTS, DEFAULT_MODELS
from dsh.llm.retry_policy import DEFAULT_CODES, MAX_TIMER_DELAY_MS


def positive():
    return z.number().step(1).min(1)


def config_schema():
    backoff = z.object({
        "initialDelayMs": z.number().max(MAX_TIMER_DELAY_MS).default(500),
        "maxDelayMs": z.number().max(MAX_TIMER_DELAY_MS).default(10000),
        "jitterRatio": z.number().min(0).max(1).default(0.1),
    })
    retry = z.union([
        z.object({"mode": z.const_("normal").required(),
                  "maxRetries": z.number().step(1).min(0).max(9007199254740991).default(5),
                  "retryableCodes": z.array(z.string()).default(DEFAULT_CODES), "backoff": backoff}),
        z.object({"mode": z.const_("always").required(), "backoff": backoff}),
    ])
    model = z.object({
        "id": z.string().required(), "name": z.string(), "description": z.string(),
        "contextWindow": positive(), "maxTokens": positive(),
        "inputModalities": z.array(z.union(["text", "image"])).min(1).default(["text"]),
        "imagePixelBudget": z.union([positive(), "low"]), "imageMaxBytes": positive(),
    })
    fields = {key: positive().default(value) for key, value in DEFAULTS.items()
              if key not in ("apiKeyEnv", "streamIdleTimeoutMs", "filesApiTimeoutMs",
                             "fileExpiresAfterSeconds", "fileRefreshMarginSeconds", "fileQuotaCleanupBatch")}
    fields.update({
        "apiKeyEnv": z.string().role("credential-ref").default(DEFAULTS["apiKeyEnv"]),
        "baseURL": z.string(), "thinking": z.union(["enabled", "disabled"]),
        "reasoningEffort": z.union(["off", "low", "high", "max"]),
        "models": z.array(model).default(DEFAULT_MODELS),
        "maxTokens": positive().max(9007199254740991).default(DEFAULTS["maxTokens"]),
        "fileExpiresAfterSeconds": z.number().step(1).min(3600).max(2592000).default(DEFAULTS["fileExpiresAfterSeconds"]),
        "fileRefreshMarginSeconds": z.number().step(1).min(0).default(DEFAULTS["fileRefreshMarginSeconds"]),
        "fileQuotaCleanupBatch": positive().max(1000).default(DEFAULTS["fileQuotaCleanupBatch"]),
        "retryPolicy": retry,
    })
    for key in ("streamIdleTimeoutMs", "filesApiTimeoutMs"):
        fields[key] = z.number().min(float.fromhex("0x0.0000000000001p-1022")).max(MAX_TIMER_DELAY_MS).default(DEFAULTS[key])
    return z.object(fields)
