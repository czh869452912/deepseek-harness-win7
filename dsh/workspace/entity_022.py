"""Current attach admission; settled membership uses registry-owned candidates."""
import os
import stat

from dsh.workspace.current import realpath_normalize
from dsh.workspace.entity import WorkspaceEntity, field


class Current022WorkspaceEntity(WorkspaceEntity):
    async def attachSession(self, session_id):
        if session_id not in self._record['sessionIds']:
            header = await self._host.read_session_header(session_id)
            cwd = field(header, 'cwd')
            prefix = "cannot attach session '%s' to workspace '%s': " % (session_id, self.path)
            if cwd is None:
                raise ValueError(prefix + 'its stored header carries no cwd to validate against')
            try:
                canonical = realpath_normalize(cwd)
            except Exception as error:
                raise ValueError(prefix + "its cwd '%s' does not resolve, so it cannot be validated" % cwd) from error
            if not stat.S_ISDIR(os.stat(canonical).st_mode):
                raise ValueError(prefix + "its cwd '%s' is not a directory" % cwd)
            if canonical != self.path:
                raise ValueError(prefix + "its cwd resolves to '%s'" % canonical)
            self._host.remember_session_path(session_id, canonical)
        await self._mutate(lambda record: record if session_id in record['sessionIds'] else
                           dict(record, sessionIds=[session_id] + record['sessionIds']))

    attach_session = attachSession
