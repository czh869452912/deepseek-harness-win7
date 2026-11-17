"""Paired fixed Source validator, install arguments, and multilingual search."""
import copy
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import rc022_events_probe as probe

URL = 'https://market.example/dsh/index.json'


def cases():
    version = dict(version='1.2.3', publishTimestamp=1790476800, source=dict(type='npm'))
    plugin = dict(name='@scope/example', versions=[version])
    base = dict(format=1, title={'en': 'Market', 'zh': '市场'}, plugins=[plugin])
    rows = []

    def add(value, url=URL, kind='parse', **extra):
        rows.append(dict(kind=kind, value=value, url=url, **extra))

    def mutate(path, value):
        document = copy.deepcopy(base)
        cursor = document
        for key in path[:-1]:
            cursor = cursor[key]
        cursor[path[-1]] = value
        add(document)

    add(base)
    for value in [None, [], True, 7, 'index', {}]:
        add(value)
    for value in [None, 0, '1', 2, True]:
        mutate(['format'], value)
    for value in [None, '', ' \t\u3000', {}, {'zh': '市'}, {'en-US': 'x'}, {'en': 9}, {'en': 'OK', 'zh-cn': '中'}]:
        mutate(['title'], value)
    for value in [None, [], {'categories': None}, {'labels': []}, {'sortKeys': {'x': {'title': 'X', 'order': 'bad'}}},
                  {'categories': {'': {'title': 'Empty'}}}, {'categories': {'__proto__': {'title': 'Safe'}}}]:
        mutate(['metadata'], value)
    for value in [None, {}, [plugin, plugin]]:
        mutate(['plugins'], value)
    for value in ['', 'UPPER', '@scope/', 'a/b', 'a' * 215, 'a' * 214, '~foo', 'a~foo']:
        mutate(['plugins', 0, 'name'], value)
    for value in [None, [], {}, [version, version]]:
        mutate(['plugins', 0, 'versions'], value)
    for value in ['v1.0.0', '01.0.0', '1.0.0-01', '1.0.0-rc.1+build.5', '99999999999999999.0.0']:
        mutate(['plugins', 0, 'versions', 0, 'version'], value)
    for value in [-1, 0, 1.5, 99999999999, 100000000000, '2', None]:
        mutate(['plugins', 0, 'versions', 0, 'publishTimestamp'], value)
    for value in [None, {}, {'dsh': None}, {'dsh': 'workspace:*'}, {'dsh': 'nonsense'}, {'dsh': '^0.2.0 || >=1.0.0'}, {'dsh': '*', 'node': 'ignored'}]:
        mutate(['plugins', 0, 'versions', 0, 'engines'], value)
    for value in [None, {}, {'type': 'other'}, {'type': 'npm', 'registry': 'https://EXAMPLE.com:443/'},
                  {'type': 'npm', 'registry': 'https://a/?q=1'}, {'type': 'npm', 'registry': 'https://u:p@a/'},
                  {'type': 'git', 'url': 'https://git.example/group/repo', 'commit': 'a'*40, 'path': 'packages/@scope/foo'},
                  {'type': 'git', 'url': 'https://git.example/group/repo.git', 'commit': 'a'*40},
                  {'type': 'git', 'url': 'https://git.example/group/repo', 'commit': 'A'*40},
                  {'type': 'git', 'url': 'http://git.example/group/repo', 'commit': 'a'*40},
                  {'type': 'git', 'url': 'https://git.example/group/repo.tar.gz', 'commit': 'a'*40},
                  {'type': 'git', 'url': 'https://git.example/group/repo', 'commit': 'a'*40, 'path': '../escape'}]:
        mutate(['plugins', 0, 'versions', 0, 'source'], value)
    for value in [None, 'icons/a.svg', '../a.png', '//cdn.example/a.png', 'http://other.example/a',
                  'https://例子.测试/a', 'data:image/png;base64,AA==', 'data:image/png;base64,',
                  'data:image/png;base64,AAA', 'data:image/svg+xml;base64,' + 'AAAA'*10923,
                  'data:image/gif;base64,AA==', 'https://u:p@a/icon#x']:
        mutate(['plugins', 0, 'icon'], value)
    for value in [None, 'http://u:p@EXAMPLE.com/a?q=1#h', 'file:///a']:
        mutate(['plugins', 0, 'homepage'], value)
    for value in [None, 'https://a/b', {'url': 'https://a/b', 'directory': 'a/../b'},
                  {'url': 'https://a/b', 'directory': '@scope/foo', 'type': 'git'}, {'url': 'https://a/b#h'}]:
        mutate(['plugins', 0, 'repository'], value)
    for value in [None, {}, {'keywords': ['', '  ']}, {'category': 'unknown'}, {'labels': ['x']},
                  {'labels': None, 'sortKeys': None}, {'sortKeys': {'unknown': None}}]:
        mutate(['plugins', 0, 'metadata'], value)
    for url in ['relative', '', 'file:///x/index.json', 'http://market.example/a/index.json',
                'https://[::1]:443/a/../index.json', 'https://例子.测试/目录/index.json']:
        add(base, url)
    document = copy.deepcopy(base)
    document['metadata'] = {'categories': {'__proto__': {'title': {'en': 'Engineering', 'zh': '工程'}}},
        'labels': {'constructor': {'title': {'en': 'Official', 'ja': '公式'}}},
        'sortKeys': {'__proto__': {'title': 'Rank', 'order': 'asc'}}}
    document['plugins'][0].update(metadata={'category': '__proto__', 'labels': ['constructor'], 'keywords': ['alpha'], 'sortKeys': {'__proto__': 0}})
    document['plugins'][0]['versions'] = [dict(version=v, publishTimestamp=i, source={'type': 'npm'})
        for i, v in enumerate(['1.0.0+z', '1.0.0+a', '1.0.0-rc.1', '1.10.0', '1.2.0'])]
    add(document)
    duplicate = copy.deepcopy(document); duplicate['plugins'][0]['metadata']['labels'] *= 2; add(duplicate)
    selections = [dict(sort={'kind': kind}) for kind in ['index', 'relevance']]
    selections += [dict(text=text, sort={'kind': 'relevance'}) for text in [
        'alpha', 'ＡＬＰＨＡ', 'enginnering', '工程', '公式', '中文插件', '国際', 'ｶﾀｶﾅ', '한글',
        'cafe\u0301', 'alpha 工程', '!!!', 'nonexistent']]
    selections += [dict(sort={'kind': kind, **extra}) for kind, extra in [
        ('published', {'direction': 'asc'}), ('published', {'direction': 'desc'}),
        ('key', {'id': '__proto__', 'direction': 'asc'}), ('key', {'id': '__proto__', 'direction': 'desc'})]]
    selections += [dict(category=category, labels=labels, sort={'kind': 'index'}) for category, labels in [
        ('__proto__', []), ('none', []), ('__proto__', ['constructor']), ('__proto__', ['unknown'])]]
    for i, title in enumerate(['中文插件', '国際カタカナ', '한글 Café', 'Alpha companion', 'alpha']):
        member = copy.deepcopy(plugin); member['name'] = 'dsh-' + str(i); member['title'] = title
        member['versions'][0]['publishTimestamp'] = i; document['plugins'].append(member)
    add(document, kind='search', selections=selections)
    # Exercise actual async chunk boundaries and lazy reuse, beyond BUILD_CHUNK.
    large = copy.deepcopy(base)
    large['plugins'] = [dict(name='dsh-item-'+str(i), title='Engineering alpha '+str(i),
        versions=[version]) for i in range(1001)]
    add(large, kind='search', selections=[dict(text='alpha', sort={'kind': 'relevance'}),
        dict(text='1000', sort={'kind': 'index'}), dict(text='engineering', sort={'kind': 'published', 'direction': 'asc'})])
    return rows


async def observe():
    from dsh.boot.market_index_022 import observe_market_operations
    return observe_market_operations(cases())


def prepare(output):
    path = output/'operations.json'
    path.write_text(json.dumps(cases(), ensure_ascii=True), encoding='utf-8')
    return [path]


if __name__ == '__main__':
    probe.native = observe
    probe.main('rc022_market_index.mts', scope='Format-1 parsed JSON validator, install specs, multilingual MiniSearch selection and 1001-document chunking; excludes UTF-8/JSON byte diagnostics, fetch/cache and service queries.',
        prepare=prepare, extra_inputs=[ROOT/'dsh/boot/market_index_022.py', ROOT/'scripts/rc022_market_index_probe.py',
            ROOT/'dsh/boot/market-index/manifest.json', ROOT/'dsh/boot/market-index/market.js',
            ROOT/'scripts/native/market-index/entry.ts', ROOT/'scripts/native/market-index/driver.js'])
