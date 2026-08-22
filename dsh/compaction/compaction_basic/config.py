from typing import Any, Dict, Optional


class ResolvedCompactionConfig:
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        cfg = config or {}
        self.threshold_tokens: int = int(cfg.get("thresholdTokens", 32000))
        self.retain_tokens: int = int(cfg.get("retainTokens", 8000))
        self.keep_recent_messages: int = int(cfg.get("keepRecentMessages", 4))
        self.model_policies: Dict[str, Any] = dict(cfg.get("modelPolicies", {}))
