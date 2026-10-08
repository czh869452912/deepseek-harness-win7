"""Audit the frozen frontend artifacts, never treating static matches as runtime proof."""
import argparse
import hashlib
import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
CAPABILITIES = {
    'AbortSignal.any': ('missing', 'Host adapter; event-based native abort algorithm limitations remain'),
    'Promise.withResolvers': ('missing', 'Host adapter'),
    'AbortSignal.timeout': ('supported', 'preserve native implementation'),
    'toSorted': ('needs-review', 'a name match may be application code, inspect call sites'),
    'toReversed': ('needs-review', 'inspect call sites'),
    'toSpliced': ('needs-review', 'inspect call sites'),
    'Object.groupBy': ('needs-review', 'inspect call sites'),
    'Map.groupBy': ('needs-review', 'inspect call sites'),
    'structuredClone': ('supported', 'real browser journey still required'),
    'findLast': ('supported', 'verified in raw fixed Chromium 108; inspect receiver types'),
    'findLastIndex': ('supported', 'verified in raw fixed Chromium 108; inspect receiver types'),
    'DecompressionStream': ('supported', 'verified in raw fixed Chromium 108; each enabled realm still needs coverage'),
    'color-mix': ('missing', 'actual bundled CSS uses it; the JavaScript adapter does not supply a CSS fallback'),
    'scrollbar-width': ('missing', 'inspect WebKit scrollbar fallback for each component'),
    'light-dark': ('callsite-review', 'unsupported in raw fixed Chromium 108; a library option string is not proof of an active CSS use'),
    'scrollend': ('fallback-review', 'absent in raw fixed Chromium 108; trajectory already guards the event and uses a debounce fallback'),
    'container-type': ('supported', 'verified in raw fixed Chromium 108; style and layout coverage still required'),
    'Worker': ('realm-review', 'each instantiated worker needs its own capability audit'),
    'SharedWorker': ('realm-review', 'each instantiated worker needs its own capability audit'),
    'iframe': ('realm-review', 'each instantiated document needs its own capability audit'),
}


def audit(root):
    manifest = json.loads((root / 'scripts/frontend-inputs.json').read_text(encoding='utf-8'))
    paths = [row['path'] for row in manifest['files'] + manifest['client_files']]
    if len(paths) != len(set(paths)):
        raise ValueError('duplicate frontend artifact')
    rows = []
    for name in paths:
        path = root / name
        data = path.read_bytes()
        expected = next(row['sha256'] for row in manifest['files'] + manifest['client_files'] if row['path'] == name)
        actual = hashlib.sha256(data).hexdigest()
        if actual != expected:
            raise ValueError('frontend artifact changed: ' + name)
        row = dict(path=name, sha256=actual, bytes=len(data), kind=path.suffix,
                   findings=[])
        if path.suffix in ('.js', '.css', '.html'):
            text = data.decode('utf-8')
            for capability, (support, adaptation) in CAPABILITIES.items():
                pattern = r'\b' + re.escape(capability) + r'\b'
                positions = [match.start() for match in re.finditer(pattern, text)]
                if positions:
                    row['findings'].append(dict(capability=capability, support=support,
                        adaptation=adaptation, occurrences=len(positions),
                        first_offsets=positions[:16]))
        rows.append(row)
    adapter = root / 'dsh/host/browser_compat/compat.js'
    return dict(target_upstream=manifest['target_upstream'], artifacts=rows,
        compatibility_sha256=hashlib.sha256(adapter.read_bytes()).hexdigest(),
        scope='All recorded shell/client bytes including dependencies embedded in bundles/maps. Static inventory only; dynamic Loader roster, actual calls, CSS behavior and enabled realm coverage require browser observations.',
        certified=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = audit(args.root.resolve())
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump(report, stream, ensure_ascii=True, indent=2)
        stream.write('\n')
    print(json.dumps(dict(artifacts=len(report['artifacts']), certified=False, output=str(args.output))))


if __name__ == '__main__':
    main()
