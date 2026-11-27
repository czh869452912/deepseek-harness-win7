"""Build an upstream format-1 index and npm metadata for reviewed Win7 packages."""
import argparse
import base64
import hashlib
import json
import shutil
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import quote, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dsh.boot.market_document_022 import normalize_index_url
from dsh.boot.market_index_022 import parse_market_index
from dsh.boot.python_directory_mutation import replace_directory
from dsh.boot.python_package_local import publish_local
from dsh.boot.semver import parse


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def build_index(output, base_url, sources, publish_timestamp, title):
    base_url = normalize_index_url(base_url).rstrip('/') + '/'
    if urlsplit(base_url).query:
        raise ValueError('The publication base URL must have no query')
    if publish_timestamp < 0:
        raise ValueError('Publication timestamp must be non-negative')
    if output.exists():
        raise FileExistsError(str(output))
    registry = base_url + 'registry/'
    releases = {}
    with TemporaryDirectory(prefix='dsh-plugin-index-', dir=str(output.parent)) as temporary:
        work = Path(temporary)
        site = work / 'site'
        for source in sources:
            with TemporaryDirectory(dir=temporary) as prepared:
                manifest = publish_local(str(work), str(source), prepared)
                name, version = manifest['name'], manifest['version']
                parse(version)
                versions = releases.setdefault(name, {})
                if version in versions:
                    raise ValueError('Duplicate release ' + name + '@' + version)
                relative = Path('packages') / name / (version + '.tgz')
                tarball = site / relative
                tarball.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(Path(prepared) / 'package.tgz'), str(tarball))
                with tarball.open('rb') as stream:
                    digest = hashlib.sha512()
                    for chunk in iter(lambda: stream.read(65536), b''):
                        digest.update(chunk)
                versions[version] = dict(manifest, dist=dict(
                    tarball=base_url + quote(relative.as_posix(), safe='/@'),
                    integrity='sha512-' + base64.b64encode(digest.digest()).decode('ascii')))

        index = dict(format=1, title=title, plugins=[])
        for name, versions in releases.items():
            ordered = sorted(versions, key=parse, reverse=True)
            latest = next((version for version in ordered if not parse(version).pre), ordered[0])
            manifest = versions[latest]
            entry = dict(name=name, versions=[])
            for key in ('description', 'homepage'):
                if isinstance(manifest.get(key), str):
                    entry[key] = manifest[key]
            author = manifest.get('author')
            if isinstance(author, str):
                entry['author'] = author
            for version in ordered:
                row = dict(version=version, publishTimestamp=publish_timestamp,
                           source=dict(type='npm', registry=registry))
                engines = versions[version].get('engines', {})
                if 'dsh' in engines:
                    row['engines'] = dict(dsh=engines['dsh'])
                entry['versions'].append(row)
            index['plugins'].append(entry)
            write_json(site / 'registry' / name,
                       {'name': name, 'versions': versions, 'dist-tags': {'latest': latest}})

        parse_market_index(index, base_url + 'index.json')
        write_json(site / 'index.json', index)
        replace_directory(str(site), str(output))
    return output / 'index.json'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--base-url', required=True)
    parser.add_argument('--title', default='DeepSeek Harness Win7')
    parser.add_argument('--publish-timestamp', type=int, required=True, help='Release time in Unix seconds')
    parser.add_argument('sources', type=Path, nargs='+', help='Reviewed native plugin directories or archives')
    args = parser.parse_args()
    print(build_index(args.output.resolve(), args.base_url,
                      [path.resolve(strict=True) for path in args.sources],
                      args.publish_timestamp, args.title))


if __name__ == '__main__':
    main()
