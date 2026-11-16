"""Projection, request snapshot, availability and inclusive QPS window contracts."""
import asyncio
import json
import sys
from contextlib import asynccontextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import rc022_events_probe as probe


def cases():
    values = [None, False, 0, 1, '', 'value', [], {}, ['x']]
    valid = dict(url='https://page.test', title='Title', snippet='Snippet', date=None)
    rows = [dict(kind='map', payload=value) for value in values]
    rows += [dict(kind='map', payload={'results': value}) for value in values]
    rows += [dict(kind='map', payload={'results': [valid, valid]})]
    for field in ('url', 'title', 'snippet', 'summary', 'date'):
        item = dict(valid); item.pop(field, None)
        rows.append(dict(kind='map', payload={'results': [item]}))
        for value in values:
            rows.append(dict(kind='map', payload={'results': [dict(valid, **{field: value})]}))
    questions = [None, '', ' \t\n ', ' first\n second\t third ', '🙂'*140, 'a'*128+'last', '\ud83d\ude00'*140, '\ud800'*140]
    questions += ['a'+chr(code)+'b' for code in (9, 10, 11, 12, 13, 32, 0xA0, 0x1680, *range(0x2000, 0x200B), 0x2028, 0x2029, 0x202F, 0x205F, 0x3000, 0xFEFF, 0x85, 0x180E, 0x200B)]
    for question in questions:
        for bound in (None, 3, 20): rows.append(dict(kind='search', question=question, bound=bound))
    for content in values+['# Title\n\nbody', '\ud800']:
        rows.append(dict(kind='fetch', payload=dict(content=content)))
    for base in ('https://api.test', 'not a url', 'http://[', 'file:///tmp', 'data:text/plain,x', 'http://127.1', 'HTTP://EXAMPLE.COM:80/a'):
        for key in ('', 'fixture-key'):
            for count in (0, 1, 1.5, 50, 51, None, False):
                rows.append(dict(kind='available', base=base, key=key, count=count))
    for now in (999, 1000, 1001):
        rows.append(dict(kind='rate', now=now, starts=[0, 0], limit=2, abort=False))
    rows.append(dict(kind='rate', now=1000, starts=[0], limit=1, abort=True))
    rows += [dict(kind='snapshot-error', provider=provider) for provider in ('search', 'fetch')]
    return rows


def prepare(output):
    path = output/'inputs.json'; path.write_text(json.dumps(cases()), encoding='utf-8'); return [path]


async def observe():
    from dsh.core.abort import AbortController
    from dsh.web import deepseek_api_providers as p
    from dsh.web import deepseek_api_transport as transport
    original = transport.fetchResponse; clock = p._now; delay = p.abortableDelay; rows = []
    try:
        for entry in cases():
            kind = entry['kind']
            if kind == 'snapshot-error':
                def fail(): raise RuntimeError('snapshot-failed')
                provider = p.DeepSeekSearchApiProvider(fail) if entry['provider'] == 'search' else p.DeepSeekFetchApiProvider(fail)
                returned = False
                try:
                    operation = getattr(provider, entry['provider'])({})
                    returned = True
                    await operation
                except Exception as error: result = dict(returned=returned, message=str(error))
            elif kind == 'map':
                try: result = p.mapSearchResponse(entry['payload'])
                except Exception as error: result = dict(code=error.code, message=error.message)
            elif kind == 'rate':
                controller = AbortController(); now = [entry['now']]; waits = []
                p._now = lambda: now[0]
                async def fakeDelay(ms, signal):
                    waits.append(ms)
                    if entry['abort']: controller.abort(RuntimeError('fixture-cancel'))
                    else: now[0] += ms
                    await asyncio.sleep(0)
                p.abortableDelay = fakeDelay
                provider = p.DeepSeekSearchApiProvider(lambda: {})
                provider.starts = list(entry['starts'])
                try:
                    await provider.waitForRequestSlot(entry['limit'], controller.signal)
                    result = dict(admitted=True)
                except Exception as error: result = dict(code=error.code, message=error.message)
                result.update(now=now[0], starts=provider.starts, waits=waits)
                p._now = clock; p.abortableDelay = delay
            else:
                key = entry.get('key', 'fixture-key'); reads = [0]; sent = []
                options = dict(auth={'sources': [dict(kind='api-key', baseURL=entry.get('base', 'https://api.test'), key=key)]},
                               count=entry.get('count', 10), requestsPerSecond=5,
                               originalQuestion=lambda: entry.get('question'),
                               guidance=dict(subject='Search', plugin='web-deepseek-api', custom=True,
                                             baseURLField='searchBaseURL', apiKeyEnvField='searchApiKeyEnv'))
                def snapshot():
                    reads[0] += 1
                    return options
                @asynccontextmanager
                async def response(endpoint, headers, body, signal):
                    sent.append(dict(path='/fetch' if kind == 'fetch' else '/search', body=json.loads(body)))
                    async def chunks():
                        yield json.dumps(entry['payload'] if kind == 'fetch' else {'results': []}).encode('utf-8')
                    yield dict(status=200), chunks()
                transport.fetchResponse = response
                search = p.DeepSeekSearchApiProvider(snapshot); fetch = p.DeepSeekFetchApiProvider(snapshot)
                if kind == 'available': result = dict(search=search.available(), fetch=fetch.available())
                else:
                    try:
                        if kind == 'fetch': operation = fetch.fetch(dict(url='https://page.test/path'))
                        else: operation = search.search(dict(query='fixture', maxResults=entry['bound']))
                        # The call captures options before a later settings mutation.
                        options = dict(options, count=49, originalQuestion=lambda: 'changed-after-call')
                        result = dict(value=await operation)
                    except Exception as error: result = dict(code=error.code, message=error.message)
                    result.update(sent=sent, reads=reads[0])
            rows.append(dict(kind=kind, result=result))
        rows.append(dict(kind='description', search=p.DeepSeekSearchApiProvider.description, fetch=p.DeepSeekFetchApiProvider.description))
        return json.loads(json.dumps(rows))
    finally:
        transport.fetchResponse = original; p._now = clock; p.abortableDelay = delay


if __name__ == '__main__':
    probe.native = observe
    probe.main('rc022_web_api_provider.mts', 'Direct Search/Fetch providers: actual decoder and request snapshots, parseable endpoints and inclusive QPS window.',
               [Path(__file__).resolve(), ROOT/'dsh/web/deepseek_api_providers.py', ROOT/'dsh/resources/web_api_descriptions_022.json'], prepare=prepare)
