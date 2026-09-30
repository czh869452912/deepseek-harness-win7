"""Validated, immutable compaction defaults and exact routed-model policies."""
import copy
import math

from dsh.core.session.json import deep_freeze


POLICY_KEYS = frozenset(("thresholdRatio", "retainRatio", "retainTokens",
                       "summarizationProvider", "summarizationModel", "maxTokens",
                       "compactionRetries", "maxOverflowRetries"))


class TargetPressureConfigError(ValueError):
    def __init__(self, target_key, message):
        super().__init__(message)
        self.target_key = target_key
        self.targetKey = target_key


def _integer(value, positive=False):
    return (type(value) in (int, float) and math.isfinite(value)
            and value == math.floor(value) and value >= (1 if positive else 0))


def _keys(config, allowed, name):
    if not isinstance(config, dict):
        raise ValueError(name + " must be an object")
    for key in config:
        if key not in allowed:
            raise ValueError('{}: unknown key "{}"'.format(name, key))


def _policy(config, name):
    for key in ("thresholdRatio", "retainRatio"):
        if key in config:
            value = config[key]
            if type(value) not in (int, float) or not math.isfinite(value) or not 0 < value <= 1:
                raise ValueError(name + "." + key + " must be a number in (0, 1]")
    for key in ("retainTokens", "maxTokens", "compactionRetries", "maxOverflowRetries"):
        if key in config and not _integer(config[key], positive=key == "maxTokens"):
            raise ValueError(name + "." + key + " must be a "
                             + ("positive" if key == "maxTokens" else "non-negative") + " integer")
    if "retainRatio" in config and "retainTokens" in config:
        raise ValueError(name + ": retainRatio and retainTokens are mutually exclusive")
    for key in ("summarizationProvider", "summarizationModel"):
        if key in config and not isinstance(config[key], str):
            raise ValueError(name + "." + key + " must be a string")
    if "summarizationProvider" in config or "summarizationModel" in config:
        if ("summarizationProvider" not in config or "summarizationModel" not in config
                or bool(config["summarizationProvider"]) != bool(config["summarizationModel"])):
            raise ValueError(name + ": summarizationProvider and summarizationModel must be set together as an empty or non-empty pair")


def _retention(config, fallback):
    if "retainTokens" in config:
        return dict(retainTokens=config["retainTokens"])
    if "retainRatio" in config:
        return dict(retainRatio=config["retainRatio"])
    return dict(fallback)


def _ratio_retention(threshold, retention, name):
    if "retainRatio" in retention and retention["retainRatio"] >= threshold:
        raise ValueError("{}: retainRatio ({}) must be less than the resolved thresholdRatio ({})".format(
            name, retention["retainRatio"], threshold))


def resolve_config(config=None):
    config = {} if config is None else config
    name = "BasicCompactionConfig"
    _keys(config, POLICY_KEYS | {"auto", "modelPolicies"}, name)
    _policy(config, name)
    if "auto" in config and type(config["auto"]) is not bool:
        raise ValueError(name + ": auto must be a boolean")
    threshold = config.get("thresholdRatio", 0.8)
    retention = _retention(config, dict(retainRatio=0.16))
    _ratio_retention(threshold, retention, name)
    policies = config.get("modelPolicies", [])
    if not isinstance(policies, list):
        raise ValueError(name + ": modelPolicies must be an array")
    seen = set()
    for index, policy in enumerate(policies):
        scope = name + ": modelPolicies[{}]".format(index)
        _keys(policy, POLICY_KEYS | {"provider", "model"}, scope)
        for key in ("provider", "model"):
            if not isinstance(policy.get(key), str) or not policy[key]:
                raise ValueError(scope + "." + key + " must be a non-empty string")
        _policy(policy, scope)
        # A tuple retains exact route identity even when either string contains NUL.
        identity = (policy["provider"], policy["model"])
        if identity in seen:
            raise ValueError(name + ": duplicate model policy for " + "/".join(identity))
        seen.add(identity)
        _ratio_retention(policy.get("thresholdRatio", threshold), _retention(policy, retention), scope)
    resolved = dict(thresholdRatio=threshold, summarizationProvider=config.get("summarizationProvider", ""),
                    summarizationModel=config.get("summarizationModel", ""), maxTokens=config.get("maxTokens", 8192),
                    compactionRetries=config.get("compactionRetries", 1), maxOverflowRetries=config.get("maxOverflowRetries", 1),
                    modelPolicies=copy.deepcopy(policies), auto=config.get("auto", True))
    resolved.update(retention)
    return deep_freeze(resolved)


def resolve_target_policy(config, target):
    override = next((policy for policy in config["modelPolicies"]
                     if policy["provider"] == target["provider"] and policy["model"] == target["model"]), {})
    resolved = dict(target=dict(provider=target["provider"], model=target["model"]))
    for key in POLICY_KEYS - {"retainTokens", "retainRatio"}:
        resolved[key] = override.get(key, config[key])
    resolved.update(_retention(override, _retention(config, {})))
    return deep_freeze(resolved)


def resolve_compact_spec(policy, context_window):
    target_key = policy["target"]["provider"] + "/" + policy["target"]["model"]
    if not _integer(context_window, positive=True):
        raise TargetPressureConfigError(target_key, "BasicCompactionConfig: contextWindow ({}) must be a positive integer".format(context_window))
    threshold = math.floor(context_window * policy["thresholdRatio"])
    retained = policy.get("retainTokens")
    if retained is None:
        retained = math.floor(context_window * policy["retainRatio"])
    if retained >= threshold:
        raise TargetPressureConfigError(target_key, "BasicCompactionConfig: {} retainTokens ({}) must be less than threshold tokens {}".format(target_key, retained, threshold))
    resolved = {key: copy.deepcopy(value) for key, value in policy.items() if key != "retainRatio"}
    resolved.update(contextWindow=context_window, thresholdTokens=threshold, retainTokens=retained)
    return deep_freeze(resolved)


class ResolvedCompactionConfig:
    """Attribute view retained for internal callers; public configuration is immutable JSON."""
    def __init__(self, config=None):
        self.values = resolve_config(config)

    @property
    def summarization_provider(self):
        return self.values["summarizationProvider"]

    @property
    def summarization_model(self):
        return self.values["summarizationModel"]

    @property
    def max_tokens(self):
        return self.values["maxTokens"]
