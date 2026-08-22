from typing import Any, Dict, List


def summarize_compactable_messages(messages: List[Dict[str, Any]]) -> str:
    """Summarizes a set of compactable messages into a structured summary block."""
    if not messages:
        return "No prior conversation to summarize."

    summary_lines = ["# Summary of Earlier Conversation"]
    for msg in messages:
        role = msg.get("role", "unknown")
        content = str(msg.get("content", ""))
        snippet = content[:150].replace("\n", " ") + ("..." if len(content) > 150 else "")
        summary_lines.append(f"- **{role}**: {snippet}")

    return "\n".join(summary_lines)
