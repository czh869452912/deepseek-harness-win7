import argparse
import asyncio
import copy
import json
from pathlib import Path
import platform
import sys


parser = argparse.ArgumentParser()
parser.add_argument('output', type=Path)
parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[2])
arguments = parser.parse_args()
ROOT = arguments.root.resolve()
sys.path.insert(0, str(ROOT))
from dsh.cordis.context import Context
from dsh.core.session import SessionHeader, SessionPlugin
from dsh.session import icu_collation
from dsh.session.icu_collation import IcuCollator
from dsh.session.query_engine import normalized_identity, SqliteSessionQueryEngine


VALUES = ['', 'a', 'A', 'á', 'a\u0301', 'ä', 'z', '中', '文', '阿', '😀', '🐍', '\ud800', '\udc00', 'a\0b', 'ab', 'a\u200bb', 'a\u00adb', '10', '2', '-', '_', 'é', 'e\u0301', 'Å', 'å', 'Ａ', 'ａ', 'ß', 'ss', 'İ', 'i', 'ı', '💻', '👩\u200d💻', '👩💻', '\u034f', '\u2060', 'a\u0315\u0300', 'a\u0300\u0315', '\u00e0\u0315', 'a\u0300\u034f\u0315', 'a\u2060b']


async def observe():
    collator = IcuCollator()
    try:
        comparisons = [[left, right, collator.compare(left, right)] for left in VALUES for right in VALUES]
        identity = collator.runtime_identity()
    finally:
        collator.close()
    lists = [VALUES, list(reversed(VALUES))] + [[None, value, VALUES[(index + 1) % len(VALUES)]]
                                               for index, value in enumerate(VALUES)]
    fingerprints = []
    for values in lists:
        for clauses in ([dict(kind='cwd', values=values)],
                        [dict(kind='cwd', values=values), dict(kind='cwd', values=list(reversed(values)))]):
            requests = [dict(query='needle', sessionFilters=clauses, eventFilters=[], limit=1),
                        dict(sessionId='中😀', query='needle', filters=[dict(clause, kind='type', values=[value for value in clause['values'] if value is not None]) for clause in clauses], limit=1)]
            for request in requests:
                fingerprints.append(dict(request=copy.deepcopy(request), fingerprint=normalized_identity(request)))
    cursors = []
    pairs = [('nfc', ['é', 'e\u0301']), ('zero-width', ['ab', 'a\u200bb']),
             ('soft-hyphen', ['ab', 'a\u00adb']), ('word-joiner', ['ab', 'a\u2060b']),
             ('canonical-order', ['a\u0315\u0300', '\u00e0\u0315'])]
    for name, values in pairs:
        context = Context()
        await context.plugin(SessionPlugin)
        entries = [dict(header=SessionHeader('beta' if index else 'alpha', created_at=1, cwd=cwd),
                        events=[dict(type='user/message', seq=0, time=1, surfaceOp='append',
                                     data=dict(id='message-0', role='user', content=[dict(type='text', text='needle')],
                                               source=dict(kind='user')))]) for index, cwd in enumerate(values)]
        class Persistence:
            async def listSnapshots(self, signal=None):
                return [dict(header=copy.deepcopy(entry['header']), revision='1') for entry in entries]
            async def inspect(self, session_id, signal=None):
                entry = next(entry for entry in entries if entry['header'].id == session_id)
                return dict(meta=copy.deepcopy(entry['header']), events=copy.deepcopy(entry['events']))
        context.provide('sessionPersistence', Persistence())
        query = SqliteSessionQueryEngine(context, dict(path=':memory:', openAt='first-search', defaultLimit=1, maxLimit=2))
        try:
            request = dict(query='needle', sessionFilters=[dict(kind='cwd', values=values)], limit=1)
            first = await query.searchSessions(request)
            same = await query.searchSessions(dict(request, cursor=first['nextCursor']))
            try:
                page = await query.searchSessions(dict(request, sessionFilters=[dict(kind='cwd', values=list(reversed(values)))], cursor=first['nextCursor']))
                changed = dict(ids=[item['header'].id for item in page['items']])
            except Exception as error:
                changed = dict(code=getattr(error, 'code', None), message=getattr(error, 'message', str(error)))
            cursors.append(dict(name=name, first=[item['header'].id for item in first['items']],
                                same=[item['header'].id for item in same['items']], reversed=changed))
        finally:
            await query.close()
            await context.fiber.dispose()
    return dict(root=str(ROOT), moduleFile=str(Path(icu_collation.__file__).resolve()), python=platform.python_version(),
                runtime=identity, observations=dict(comparisons=comparisons, fingerprints=fingerprints, cursors=cursors))


arguments.output.write_text(json.dumps(asyncio.run(observe()), ensure_ascii=True, indent=2)+'\n', encoding='utf-8')
