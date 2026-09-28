"""Public product identity shared by provider transports."""
from dsh import __version__


def attribution_headers():
    return {"User-Agent": "deepseek-harness/{} (+https://github.com/deepseek-ai/deepseek-harness)".format(__version__)}
