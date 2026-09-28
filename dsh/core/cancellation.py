"""Read the shared AbortSignal/asyncio.Event cancellation contract."""


def aborted(signal):
    return bool(signal is not None and (getattr(signal, "aborted", False) or
                (callable(getattr(signal, "is_set", None)) and signal.is_set())))
