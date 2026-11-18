"""Current Source/Native readers against the same live Win32 shared holders."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.rc022_office_runtime_probe import run_observer
from scripts import rc022_jsonl_sharing_contract as contract


def main():
    parser = argparse.ArgumentParser()
    for name in ('source', 'node', 'output'):parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    if args.source.resolve() != (ROOT / 'reference').resolve():
        raise ValueError('Sharing Source must be the actual current installation reference')
    if subprocess.check_output([str(args.node), '--version'], encoding='utf-8').strip() != 'v24.9.0':
        raise ValueError('Pinned Node24 required')
    contract.source_pin()
    output = args.output.resolve();output.mkdir(parents=True)
    env = dict(os.environ, PATH=str(args.node.resolve().parent) + os.pathsep + os.environ['PATH'])
    command = [sys.executable, str(ROOT / 'scripts/rc022_jsonl_sharing_contract.py'), '--output', str(output / 'pair.json')]
    with (output / 'run.log').open('wb') as log:code = run_observer(command, ROOT, env, log, timeout=180)
    report = dict(status='failed', command=command, exit_code=code,
                  scope='Actual current-v4 Source/Native complete same-file list/read/raw bytes and physical revisions with four live Win32 shared holders')
    try:
        if code:raise RuntimeError('Current physical sharing contract failed')
        value = json.loads((output / 'pair.json').read_text(encoding='utf-8'))
        if value['status'] != 'matched' or value['cases'] != 4:raise ValueError('Complete four sharing contracts required')
        report.update(status='passed', observations=4, source_exit_code=0,
            inputs={name:hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in contract.SOURCE_INPUTS})
    finally:
        (output / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    return 0


if __name__ == '__main__':raise SystemExit(main())
