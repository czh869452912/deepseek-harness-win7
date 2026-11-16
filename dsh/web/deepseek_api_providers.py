"""Direct Search/Fetch API providers with per-operation snapshots and QPS admission."""
import asyncio
import json
import math
import re
import time
from pathlib import Path

from dsh.cordis.awaiting import start_coroutine
from dsh.core.cancellation import aborted, subscribe_abort
from dsh.host.http_proxy_policy import JS_SPACE
from dsh.host.url_current import _url
from dsh.web.deepseek_api_transport import dispatchDeepSeekWeb, hasDeepSeekWebCredential, invalidResponse, searchAborted
from dsh.web.web_service import WebSearchProvider, WebFetchProvider

DEEPSEEK_SEARCH_API_PROVIDER_ID = 'deepseek-search-api'
DEEPSEEK_FETCH_API_PROVIDER_ID = 'deepseek-fetch-api'
DEEPSEEK_WEB_API_BASE_URL = 'https://api.deepseek.com/v1/tools'
DEEPSEEK_DEFAULT_COUNT = 10
DEEPSEEK_SEARCH_REQUESTS_PER_SECOND = 5
with (Path(__file__).resolve().parents[1]/'resources/web_api_descriptions_022.json').open(encoding='utf-8') as _stream:
    _DESCRIPTIONS = json.load(_stream)


def mapSearchResponse(response):
    if not isinstance(response, dict) or not isinstance(response.get('results'), list):
        raise invalidResponse()
    sources = []
    for item in response['results']:
        if (not isinstance(item, dict) or not isinstance(item.get('url'), str) or not item['url']
            or not isinstance(item.get('title'), str) or not isinstance(item.get('snippet'), str)
            or ('summary' in item and not isinstance(item['summary'], str))
            or 'date' not in item or (item['date'] is not None and not isinstance(item['date'], str))):
            raise invalidResponse()
        source = dict(url=item['url'])
        for key, output in (('title', 'title'), ('snippet', 'snippet'), ('summary', 'summary'), ('date', 'publishedAt')):
            if item.get(key): source[output] = item[key]
        sources.append(source)
    return dict(sources=sources, truncated=False)


def boundedQuestion(question):
    if question is None: return None
    value = re.sub('['+re.escape(JS_SPACE)+']+', ' ', question).strip(' ')
    if not value: return None
    # Array.from iterates Unicode code points, preserving lone surrogates.
    return value.encode('utf-16-le', 'surrogatepass').decode('utf-16-le', 'surrogatepass')[:128]


def _positiveInteger(value):
    return type(value) in (int, float) and math.isfinite(value) and value > 0 and int(value) == value


def _now():
    return time.monotonic()*1000


def _parseableSources(auth):
    try:
        for source in auth['sources']:
            if source['kind'] != 'misconfigured': _url(source['baseURL'])
        return True
    except (ValueError, TypeError):
        return False


async def abortableDelay(ms, signal):
    loop = asyncio.get_running_loop(); future = loop.create_future()
    def finish(_reason=None):
        if not future.done(): future.set_result(None)
    timer = loop.call_later(max(0, ms)/1000, finish)
    dispose = subscribe_abort(signal, finish)
    try: await future
    finally:
        timer.cancel(); dispose()


class DeepSeekSearchApiProvider(WebSearchProvider):
    id = DEEPSEEK_SEARCH_API_PROVIDER_ID
    description = _DESCRIPTIONS['search']

    def __init__(self, resolveOptions):
        self.resolveOptions = resolveOptions
        self.starts = []

    def available(self):
        options = self.resolveOptions()
        return (hasDeepSeekWebCredential(options['auth']) and _parseableSources(options['auth'])
                and _positiveInteger(options['count']) and _positiveInteger(options['requestsPerSecond']))

    def search(self, request, signal=None):
        return start_coroutine(self._search(request, signal))

    async def _search(self, request, signal):
        options = self.resolveOptions()
        question = boundedQuestion(options['originalQuestion']()) if options.get('originalQuestion') else None
        body = dict(query=request['query'], count=min(options['count'], request.get('maxResults') if request.get('maxResults') is not None else options['count']), need_content=False)
        if question is not None: body['ori_question'] = question
        return await dispatchDeepSeekWeb(options['auth'], dict(path='/search', body=body,
            decode=mapSearchResponse, waitToSend=lambda signal: self.waitForRequestSlot(options['requestsPerSecond'], signal),
            guidance=options['guidance']), signal)

    async def waitForRequestSlot(self, limit, signal):
        while True:
            if aborted(signal): raise searchAborted(signal)
            now = _now()
            while self.starts and self.starts[0] < now-1000: self.starts.pop(0)
            if not self.starts or len(self.starts) < limit:
                self.starts.append(now)
                return
            await abortableDelay(self.starts[0]+1001-now, signal)


class DeepSeekFetchApiProvider(WebFetchProvider):
    id = DEEPSEEK_FETCH_API_PROVIDER_ID
    description = _DESCRIPTIONS['fetch']

    def __init__(self, resolveOptions):
        self.resolveOptions = resolveOptions

    def available(self):
        options = self.resolveOptions()
        return hasDeepSeekWebCredential(options['auth']) and _parseableSources(options['auth'])

    def fetch(self, request, signal=None):
        options = self.resolveOptions()
        def decode(payload):
            if not isinstance(payload, dict) or not isinstance(payload.get('content'), str): raise invalidResponse()
            return dict(url=request['url'], statusCode=200, body=dict(kind='text', content=payload['content']), truncated=False)
        return start_coroutine(dispatchDeepSeekWeb(options['auth'], dict(path='/fetch', body=dict(url=request['url']),
                               decode=decode, guidance=options['guidance']), signal))
