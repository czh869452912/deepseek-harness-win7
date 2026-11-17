"""Copy the fixed Source's byte-preserved recurrence library into its private port."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

TARGET='38a6a5c965aa99ab525161efb7cc5cf1fe62fced'
ROOT=Path(__file__).resolve().parents[1]


def prepare(source):
    assert subprocess.check_output(['git','-C',str(source),'rev-parse','HEAD'],encoding='utf-8').strip()==TARGET
    package=source/'node_modules/.pnpm/rrule@2.8.1/node_modules/rrule'
    assert json.loads((package/'package.json').read_text(encoding='utf-8'))['version']=='2.8.1'
    output=ROOT/'dsh/javascript/rrule';inputs={}
    expected={'dist/es5/rrule.min.js':'f125534233e976a287691398c72b875fd2344837bce560142379b73009ca3427',
        'LICENCE':'6c12f89b62fce4d9a75629a68086f1bcf0192a2ce678d2caadd9f86aa1a0fa58'}
    for relative,name in [('dist/es5/rrule.min.js','rrule.min.js'),('LICENCE','LICENCE')]:
        raw=(package/relative).read_bytes();digest=hashlib.sha256(raw).hexdigest()
        assert digest==expected[relative], 'Pinned RRULE input bytes differ'
        (output/name).write_bytes(raw);inputs[relative]=digest
    resources={name:hashlib.sha256((output/name).read_bytes()).hexdigest() for name in ['rrule.min.js','LICENCE','driver.js']}
    manifest=dict(target_upstream=TARGET,package='rrule',version='2.8.1',license='BSD-3-Clause',inputs=inputs,resources=resources)
    raw=(json.dumps(manifest,indent=2)+'\n').encode('utf-8');(output/'manifest.json').write_bytes(raw)
    digest=hashlib.sha256(raw).hexdigest();print(digest)
    return digest


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--source',type=Path,required=True)
    prepare(parser.parse_args().source.resolve())
