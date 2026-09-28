"""Provider-owned retry configuration matching the pinned LLM contract."""
import copy
import math

DEFAULT_CODES = ["EMPTY_RESPONSE", "RATE_LIMIT", "SERVER", "TIMEOUT", "TRANSPORT"]
MAX_TIMER_DELAY_MS = 2147483647


def resolve_retry_policy(config=None):
    config = {"mode": "normal"} if config is None else copy.deepcopy(config)
    if not isinstance(config, dict) or config.get("mode") not in ("normal", "always"):
        raise ValueError('retryPolicy.mode must be "normal" or "always"')
    unknown = set(config) - {"mode", "maxRetries", "retryableCodes", "backoff"}
    if unknown:
        raise ValueError("retryPolicy: unknown key " + sorted(unknown)[0])
    backoff = config.get("backoff", {})
    if not isinstance(backoff, dict) or set(backoff) - {"initialDelayMs", "maxDelayMs", "jitterRatio"}:
        raise ValueError("retryPolicy.backoff: invalid keys")
    result = dict(mode=config["mode"], initialDelayMs=backoff.get("initialDelayMs", 500),
                  maxDelayMs=backoff.get("maxDelayMs", 10000), jitterRatio=backoff.get("jitterRatio", 0.1))
    for key in ("initialDelayMs", "maxDelayMs", "jitterRatio"):
        value = result[key]
        if type(value) not in (float, int) or not math.isfinite(value):
            raise ValueError("retryPolicy." + key + " must be finite")
        if not (0 <= value <= 1 if key == "jitterRatio" else 0 < value <= MAX_TIMER_DELAY_MS):
            raise ValueError("retryPolicy." + key + " is out of range")
    if result["initialDelayMs"] > result["maxDelayMs"]:
        raise ValueError("initialDelayMs must not exceed maxDelayMs")
    if result["mode"] == "normal":
        retries, codes = config.get("maxRetries", 5), config.get("retryableCodes", DEFAULT_CODES)
        if type(retries) is not int or not 0 <= retries <= 9007199254740991:
            raise ValueError("maxRetries must be a non-negative safe integer")
        if not isinstance(codes, list) or not codes or any(not isinstance(c, str) or not c for c in codes) or len(set(codes)) != len(codes):
            raise ValueError("retryableCodes must be distinct non-empty strings")
        result.update(maxRetries=retries, retryableCodes=list(codes))
    return result
