"""Validated detached DeepSeek connection snapshots, including image budgets."""
import copy
import math

from dsh.llm.retry_policy import resolve_retry_policy, MAX_TIMER_DELAY_MS

DEFAULT_MODELS = [
    {"id": "deepseek-v4-flash", "name": "DeepSeek-V4-Flash", "contextWindow": 1000000,
     "description": "Fast, efficient, and economical; suited to focused, routine, or parallel tasks."},
    {"id": "deepseek-v4-pro", "name": "DeepSeek-V4-Pro", "contextWindow": 1000000,
     "description": "Stronger agentic coding, knowledge, and difficult reasoning; suited to complex or quality-critical tasks at higher cost."},
    {"id": "deepseek-v4-flash-vision-exp", "name": "DeepSeek-V4-Flash-Vision-Exp",
     "contextWindow": 1000000, "inputModalities": ["text", "image"], "imagePixelBudget": 640000, "imageMaxBytes": 1048576},
]
DEFAULTS = dict(apiKeyEnv="DEEPSEEK_API_KEY", maxTokens=256000, defaultContextWindow=1000000,
                streamIdleTimeoutMs=300000, maxRequestFilesBytes=128 * 1024 * 1024,
                maxInlineRequestImageBytes=20 * 1024 * 1024, maxImagesPerRequest=600,
                imageOffloadByteQuantum=64 * 1024 * 1024, inlineImageOffloadByteQuantum=10 * 1024 * 1024,
                imageOffloadCountQuantum=20, filesApiTimeoutMs=60000, fileExpiresAfterSeconds=604800,
                fileRefreshMarginSeconds=3600, fileQuotaCleanupBatch=100)


class DeepSeekConfigError(ValueError):
    name = "Error"

    def __init__(self, message):
        super().__init__(message)
        self.message = message


def integer(value, field, minimum=1, maximum=9007199254740991):
    if type(value) is not int or not minimum <= value <= maximum:
        message = " is outside its integer range"
        if field == "fileExpiresAfterSeconds":
            message = " must be an integer from 3600 through 2592000"
        elif field == "fileQuotaCleanupBatch":
            message = " must be an integer from 1 through 1000"
        raise DeepSeekConfigError("llm-deepseek: " + field + message)
    return value


def resolve_options(config, environment):
    if not isinstance(config, dict):
        raise ValueError("llm-deepseek: config must be an object")
    options = dict(DEFAULTS, **copy.deepcopy(config))
    ref = options["apiKeyEnv"]
    from dsh.credentials.credentials import credential_ref
    options["apiKeyEnv"] = credential_ref(ref)
    endpoint = environment.get("DEEPSEEK_BASE_URL")
    options.setdefault("baseURL", (endpoint.get("value") if isinstance(endpoint, dict) else endpoint.value) if endpoint is not None else "https://api.deepseek.com")
    if not isinstance(options["baseURL"], str):
        raise ValueError("llm-deepseek: baseURL must be a string")
    if options.get("thinking") not in (None, "enabled", "disabled"):
        raise ValueError("llm-deepseek: invalid thinking mode")
    if options.get("reasoningEffort") not in (None, "off", "low", "high", "max"):
        raise ValueError("llm-deepseek: invalid reasoningEffort")
    if options.get("thinking") == "disabled" and options.get("reasoningEffort") not in (None, "off"):
        raise DeepSeekConfigError('llm-deepseek: only reasoningEffort "off" can be configured when thinking is disabled')
    for field in DEFAULTS:
        if field in ("apiKeyEnv", "streamIdleTimeoutMs", "filesApiTimeoutMs"):
            continue
        integer(options[field], field, 0 if field == "fileRefreshMarginSeconds" else 1)
    for field in ("streamIdleTimeoutMs", "filesApiTimeoutMs"):
        value = options[field]
        if type(value) not in (int, float) or not math.isfinite(value) or not 0 < value <= MAX_TIMER_DELAY_MS:
            raise DeepSeekConfigError("llm-deepseek: " + field + " must be a positive finite number no greater than " + str(MAX_TIMER_DELAY_MS))
    for quantum, limit in (("imageOffloadByteQuantum", "maxRequestFilesBytes"),
                           ("inlineImageOffloadByteQuantum", "maxInlineRequestImageBytes"),
                           ("imageOffloadCountQuantum", "maxImagesPerRequest")):
        if options[quantum] > options[limit]:
            raise DeepSeekConfigError("llm-deepseek: " + quantum + " must not exceed " + limit)
    integer(options["fileExpiresAfterSeconds"], "fileExpiresAfterSeconds", 3600, 2592000)
    integer(options["fileQuotaCleanupBatch"], "fileQuotaCleanupBatch", 1, 1000)
    if options["fileRefreshMarginSeconds"] >= options["fileExpiresAfterSeconds"]:
        raise DeepSeekConfigError("llm-deepseek: fileRefreshMarginSeconds must be a non-negative integer below fileExpiresAfterSeconds")
    models, seen = copy.deepcopy(options.get("models", DEFAULT_MODELS)), set()
    if not isinstance(models, list):
        raise ValueError("llm-deepseek: models must be a list")
    for model in models:
        if not isinstance(model, dict) or not isinstance(model.get("id"), str) or not model["id"]:
            raise ValueError("llm-deepseek: model ids must be non-empty")
        if model["id"] in seen:
            raise DeepSeekConfigError('llm-deepseek: duplicate catalog model "{}"'.format(model["id"]))
        seen.add(model["id"])
        if "imageDetail" in model:
            raise ValueError("llm-deepseek: use imagePixelBudget instead of imageDetail")
        for field in ("name", "description"):
            if field in model and (not isinstance(model[field], str) or field == "name" and not model[field]):
                raise ValueError("llm-deepseek: invalid model " + field)
        for field in ("contextWindow", "maxTokens", "imageMaxBytes"):
            if field in model:
                integer(model[field], "model." + field)
        modalities = model.setdefault("inputModalities", ["text"])
        if not isinstance(modalities, list) or not modalities or any(m not in ("text", "image") for m in modalities):
            raise ValueError("llm-deepseek: invalid inputModalities")
        if len(set(modalities)) != len(modalities):
            raise DeepSeekConfigError('llm-deepseek: catalog model "{}" inputModalities must not contain duplicates'.format(model["id"]))
        if "image" not in modalities:
            if "imageMaxBytes" in model or "imagePixelBudget" in model:
                raise DeepSeekConfigError('llm-deepseek: text-only catalog model "{}" cannot declare image request limits'.format(model["id"]))
        else:
            pixel = model.get("imagePixelBudget", 640000)
            model["imagePixelBudget"] = 262144 if pixel == "low" else integer(pixel, "model.imagePixelBudget")
            model.setdefault("imageMaxBytes", 1048576)
    options["models"] = models
    options["retryPolicy"] = resolve_retry_policy(options.get("retryPolicy"), "llm-deepseek: retryPolicy")
    return options
