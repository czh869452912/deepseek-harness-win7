"""One-shot, read-only balanced transcript through a persistence handle."""
from dsh.core.session.repair import interruptedTurnClosers


async def readColdSessionLog(persistence, session_id, signal=None):
    options = None if signal is None else dict(signal=signal)
    handle = await persistence.open(session_id,'read',options)
    try:
        read = await handle.read(options=options)
    except BaseException:
        try:
            await handle.close()
        except BaseException:
            pass
        raise
    await handle.close()
    events = read['events']
    return dict(eventState=read['eventState'],header=handle.header,
                inheritedEventCount=handle.inheritedEventCount,
                events=list(events)+interruptedTurnClosers(events,format_version=handle.header['version']))
