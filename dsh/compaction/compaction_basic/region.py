from typing import Any, Dict, List, Tuple


def identify_compaction_region(
    messages: List[Dict[str, Any]],
    keep_recent_messages: int = 4,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Splits messages into (system_prefix, compactable_region, preserved_tail).
    """
    if len(messages) <= keep_recent_messages:
        return messages, [], []

    system_prefix = []
    idx = 0
    while idx < len(messages) and messages[idx].get("role") == "system":
        system_prefix.append(messages[idx])
        idx += 1

    remaining = messages[idx:]
    if len(remaining) <= keep_recent_messages:
        return system_prefix, [], remaining

    compactable_region = remaining[:-keep_recent_messages]
    preserved_tail = remaining[-keep_recent_messages:]
    return system_prefix, compactable_region, preserved_tail
