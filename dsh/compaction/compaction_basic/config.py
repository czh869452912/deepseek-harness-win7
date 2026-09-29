from typing import Any, Dict, Optional


class ResolvedCompactionConfig:
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        cfg = config or {}
        self.summarization_provider = cfg.get("summarizationProvider", "")
        self.summarization_model = cfg.get("summarizationModel", "")
        if bool(self.summarization_provider) != bool(self.summarization_model):
            raise ValueError("summarizationProvider and summarizationModel must be configured together")
        self.max_tokens = int(cfg.get("maxTokens", 8192))
        self.threshold_tokens: int = int(cfg.get("thresholdTokens", 32000))
        self.retain_tokens: int = int(cfg.get("retainTokens", 8000))
        self.keep_recent_messages: int = int(cfg.get("keepRecentMessages", 4))
        self.model_policies: Dict[str, Any] = dict(cfg.get("modelPolicies", {}))
