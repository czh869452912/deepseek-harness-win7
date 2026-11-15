"""Candidate deliverables use the current directory and canonical absolute paths."""
import math
from weakref import WeakKeyDictionary

from dsh.cordis.plugin import Plugin
from dsh.core.tools import ToolArgsError, ToolContextUnavailableError
from dsh.core.session.json import UNDEFINED
from dsh.fs.fs_local import FsError
from dsh.typert.stores import field


DESCRIPTION = (
    'Declare existing files accessible through the Session filesystem as final deliverables. '
    'When a file you create or update is an output the user asked to receive, you must call present after writing it and before your final response, including files created through Bash or code execution. '
    'Mentioning its path in your reply does not replace this call. The files must already exist. '
    'The user opens the current source files; their contents are not copied or preserved.'
)


class AuthorizedToolPresent(Plugin):
    id = '@deepseek-ai/dsh-tool-present'
    name = 'tool-present'
    inject = ['tools', 'fs', 'agents', 'workingDirectory']

    def apply(self, ctx):
        maximum = self.config.get('maxFiles', 8)
        if (type(maximum) not in (int, float) or not 1 <= maximum <= 9007199254740991
                or not math.isfinite(maximum) or int(maximum) != maximum):
            raise ValueError('present requires a positive integer maxFiles')
        pending = WeakKeyDictionary()
        file_schema = dict(type='object', additionalProperties=False,
                           properties=dict(path=dict(type='string', description='Path of an existing regular file. Relative paths use the Session working directory.'),
                                           description=dict(type='string', description='Brief description for the user.')),
                           required=['path'])

        async def execute(arguments, execution):
            agent = execution.agent
            if agent is None:
                raise ToolContextUnavailableError('present requires an agent Session')
            boundary = ctx.get('agents').turnBoundaryOf(agent.session)
            if boundary is UNDEFINED or boundary is None or boundary['openTurnStartSeq'] is None:
                raise ToolContextUnavailableError('present requires an open turn')
            if not 1 <= len(arguments['files']) <= maximum:
                raise ToolArgsError('present', ['present accepts 1 to %s files' % int(maximum)])
            cwd = await ctx.get('workingDirectory').ensure(agent, execution.signal)
            files = []
            filesystem = ctx.get('fs')
            for file in arguments['files']:
                path = file['path']
                if not path.strip('\t\n\v\f\r \u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000\ufeff'):
                    raise ToolArgsError('present', ['present requires a non-empty file path'])
                entry = await filesystem.lstat(path, dict(cwd=cwd), execution.signal)
                if entry is not None and entry is not UNDEFINED and field(entry, 'type') != 'file':
                    raise FsError('Cannot present %s: not a regular file' % path, 'FS_NOT_REGULAR_FILE')
                target = await filesystem.resolve(path, dict(cwd=cwd, signal=execution.signal))
                info = await filesystem.stat(target, execution.signal)
                if info is None or info is UNDEFINED:
                    raise FsError('Cannot present %s: file not found. Check the path, create the file if needed, and retry.' % path, 'FS_NOT_FOUND')
                if field(info, 'type') != 'file':
                    raise FsError('Cannot present %s: not a regular file' % path, 'FS_NOT_REGULAR_FILE')
                files.append(dict(file, path=filesystem.processPath(target)))
            execution.signal.throwIfAborted()
            pending[execution] = (agent.session, boundary['lastTurn'], files)
            return dict(turn=boundary['lastTurn'], files=files)

        ctx.get('tools').register(dict(
            name='present', description=DESCRIPTION,
            parameters=dict(type='object', properties=dict(files=dict(type='array', items=file_schema)), required=['files']),
            output=dict(schema=dict(type='object', additionalProperties=False,
                                    properties=dict(turn=dict(type='integer'), files=dict(type='array', items=file_schema)),
                                    required=['turn', 'files']),
                        render=lambda arguments, value: [dict(type='text', text='\n'.join('Presented ' + file['path'] for file in value['files']))]),
            execute=execute))

        def result(execution, outcome):
            delivery = pending.pop(execution, None)
            if delivery is None or outcome.isError:
                return
            session, turn, files = delivery
            session.append('deliverables/presented', dict(turn=turn, callId=execution.callId, files=files))

        ctx.on('tools/result', result)
