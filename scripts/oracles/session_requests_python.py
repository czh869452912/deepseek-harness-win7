import argparse
import asyncio
import copy
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[2]
arguments = None
if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('output', type=Path)
    parser.add_argument('--root', type=Path, default=ROOT)
    arguments = parser.parse_args()
    ROOT = arguments.root.resolve()
sys.path.insert(0, str(ROOT))
import dsh
from dsh.cordis import Context
from dsh.core.abort import AbortController
from dsh.core.session.session import SessionPlugin
from dsh.session.session_query import SessionQueryService, quote_fts_data, sanitize_fts_text, make_snippet
from dsh.session.query_requests import normalize_session_request, normalize_event_request
from dsh.session.query_requests import build_session_where, build_event_where, assert_binding_count, assert_predicate_count


async def observe():
    cases = json.loads((Path(__file__).parent/'session_requests_cases.json').read_text(encoding='utf-8'))
    rows = []
    for item in cases:
        request = copy.deepcopy(item.get('request'))
        if item.get('special') == 'nan':
            request['limit'] = float('nan')
        if item.get('special') == 'infinity':
            request['limit'] = float('inf')
        observed = {}
        context = query = None
        try:
            mode = item['mode']
            if mode in ('session','event'):
                observed['value'] = (normalize_session_request if mode == 'session' else normalize_event_request)(
                    request,item.get('limits',dict(defaultLimit=2,maxLimit=3)))
                if item.get('mutate'):
                    request['sessionFilters'][0]['values'][0] = 'foreign'
            elif mode.endswith('-sql'):
                value = (build_session_where if mode == 'session-sql' else build_event_where)(item['filters'])
                observed['value'] = value
                connection = sqlite3.connect(':memory:')
                try:
                    connection.execute('CREATE TABLE docs(session_id TEXT,cwd TEXT,parent_session TEXT,created_at INTEGER,live INTEGER,persisted INTEGER,seq INTEGER,time INTEGER,type TEXT,surface TEXT)')
                    connection.executemany('INSERT INTO docs VALUES(?,?,?,?,?,?,?,?,?,?)',[
                        ('a','/workspace',None,10,1,0,1,100,'message/created','current'),
                        ('b',None,'a',20,0,1,2,200,'turn/start','log-only'),
                        ('c','/workspace','a',30,1,1,3,300,'message/created','shadowed'),
                    ])
                    where = ' WHERE '+value['sql'] if value['sql'] else ''
                    observed['matches'] = [row[0] for row in connection.execute(
                        'SELECT session_id FROM docs'+where+' ORDER BY session_id',value['params'])]
                finally:
                    connection.close()
            elif mode in ('outer','binding'):
                (assert_predicate_count if mode == 'outer' else assert_binding_count)(item['count'])
                observed['value'] = 'accepted'
            elif mode == 'snippet':
                observed['value'] = make_snippet(item['text'],item['maxChars'])
            elif mode == 'quote':
                observed['value'] = quote_fts_data(item['text'])
            elif mode == 'sanitize':
                observed['value'] = sanitize_fts_text(item['text'])
            else:
                context = Context()
                await context.plugin(SessionPlugin)
                observed['lists'] = 0
                class Persistence:
                    async def list(self, signal=None):
                        observed['lists'] += 1
                        raise AssertionError('unexpected persistence access')
                context.provide('sessionPersistence',Persistence())
                query = SessionQueryService(context,open_at=item['openAt'])
                observed['opened'] = False
                controller = AbortController()
                if item.get('abort'):
                    controller.abort(TypeError('caller abort reason'))
                await query.searchSessions(request,dict(signal=controller.signal))
                raise AssertionError('validation unexpectedly succeeded')
        except Exception as error:
            observed['error'] = dict(name=type(error).__name__,message=getattr(error,'message',str(error)),
                                     code=getattr(error,'code',None))
        finally:
            if query is not None:
                observed['opened'] = query._conn is not None
                query.close()
            if context is not None:
                await context.fiber.dispose()
        rows.append(dict(name=item['name'],observed=observed))
    return rows


def main():
    observations = asyncio.run(observe())
    report = dict(observations=observations,root=str(ROOT),module=str(Path(dsh.__file__).resolve()),
                  python=list(sys.version_info[:3]))
    arguments.output.write_text(json.dumps(report,ensure_ascii=True,indent=2)+'\n',encoding='utf-8')


if __name__ == '__main__':
    main()
