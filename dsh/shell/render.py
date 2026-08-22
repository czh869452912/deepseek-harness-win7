import re
from typing import Any, Dict


def parse_exit_status(text: str) -> Dict[str, Any]:
    """
    Split a rendered shell-tool result string into its output body and the
    structured exit status — the inverse of the `[exit code: N]` /
    `[killed by signal: X]` markers the shell tools' renderers append.
    """
    sig_match = re.search(r"\n\[killed by signal: ([^\]\n]+)\]$", text)
    if sig_match:
        return {"body": text[:sig_match.start()], "signal": sig_match.group(1)}
    exit_match = re.search(r"\n\[exit code: (\d+)\]$", text)
    if exit_match:
        return {"body": text[:exit_match.start()], "exit_code": int(exit_match.group(1))}
    return {"body": text, "exit_code": 0}
