"""Validated detached DeepSeek connection snapshots, including image budgets."""
import copy
import math

from dsh.llm.retry_policy import resolve_retry_policy, MAX_TIMER_DELAY_MS

DEFAULT_MODELS = [
    {"id": "deepseek-v4-flash", "name": "DeepSeek-V4-Flash"},
    {"id": "deepseek-v4-pro", "name": "DeepSeek-V4-Pro"},
    {"id": "deepseek-v4-flash-vision-exp", "name": "DeepSeek-V4-Flash-Vision-Exp",
     "inputModalities": ["text", "image"], "imagePixelBudget": 640000, "imageMaxBytes": 1048576},
]
DEFAULTS = dict(apiKeyEnv="DEEPSEEK_API_KEY", maxTokens=256000, defaultContextWindow=1000000,
                streamIdleTimeoutMs=300000, maxRequestFilesBytes=128 * 1024 * 1024,
                maxInlineRequestImageBytes=20 * 1024 * 1024, maxImagesPerRequest=600,
                imageOffloadByteQuantum=64 * 1024 * 1024, inlineImageOffloadByteQuantum=10 * 1024 * 1024,
                imageOffloadCountQuantum=20, filesApiTimeoutMs=60000, fileExpiresAfterSeconds=604800,
                fileRefreshMarginSeconds=3600, fileQuotaCleanupBatch=100)


def integer(value, field, minimum=1, maximum=9007199254740991):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError("llm-deepseek: " + field + " is outside its integer range")
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
        raise ValueError("llm-deepseek: thinking disabled requires effort off")
    for field in DEFAULTS:
        if field in ("apiKeyEnv", "streamIdleTimeoutMs", "filesApiTimeoutMs"):
            continue
        integer(options[field], field, 0 if field == "fileRefreshMarginSeconds" else 1)
    for field in ("streamIdleTimeoutMs", "filesApiTimeoutMs"):
        value = options[field]
        if type(value) not in (int, float) or not math.isfinite(value) or not 0 < value <= MAX_TIMER_DELAY_MS:
            raise ValueError("llm-deepseek: " + field + " must be a positive bounded timer")
    for quantum, limit in (("imageOffloadByteQuantum", "maxRequestFilesBytes"),
                           ("inlineImageOffloadByteQuantum", "maxInlineRequestImageBytes"),
                           ("imageOffloadCountQuantum", "maxImagesPerRequest")):
        if options[quantum] > options[limit]:
            raise ValueError("llm-deepseek: " + quantum + " exceeds " + limit)
    integer(options["fileExpiresAfterSeconds"], "fileExpiresAfterSeconds", 3600, 2592000)
    integer(options["fileQuotaCleanupBatch"], "fileQuotaCleanupBatch", 1, 1000)
    if options["fileRefreshMarginSeconds"] >= options["fileExpiresAfterSeconds"]:
        raise ValueError("llm-deepseek: file refresh margin must be below expiry")
    models, seen = copy.deepcopy(options.get("models", DEFAULT_MODELS)), set()
    if not isinstance(models, list):
        raise ValueError("llm-deepseek: models must be a list")
    for model in models:
        if not isinstance(model, dict) or not isinstance(model.get("id"), str) or not model["id"]:
            raise ValueError("llm-deepseek: model ids must be non-empty")
        if model["id"] in seen:
            raise ValueError("llm-deepseek: duplicate model id")
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
        if not isinstance(modalities, list) or not modalities or any(m not in ("text", "image") for m in modalities) or len(set(modalities)) != len(modalities):
            raise ValueError("llm-deepseek: invalid inputModalities")
        if "image" not in modalities:
            if "imageMaxBytes" in model or "imagePixelBudget" in model:
                raise ValueError("llm-deepseek: text model cannot declare image limits")
        else:
            pixel = model.get("imagePixelBudget", 640000)
            model["imagePixelBudget"] = 262144 if pixel == "low" else integer(pixel, "model.imagePixelBudget")
            model.setdefault("imageMaxBytes", 1048576)
    options["models"] = models
    options["retryPolicy"] = resolve_retry_policy(options.get("retryPolicy"))
    return options
