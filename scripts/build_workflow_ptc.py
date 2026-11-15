"""Rebuild the private Workflow carrier from the frozen Source and reviewed shim.

Development Python only; generated resources target the shipped Win7 worker.
Does not overwrite an output directory or change the legacy Workflow resources.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

TARGET='38a6a5c965aa99ab525161efb7cc5cf1fe62fced'
ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();source=args.source.resolve();output=args.output.resolve()
    if output.exists():raise ValueError('workflow carrier output must be new')
    assert subprocess.check_output(['git','-C',str(source),'rev-parse','HEAD'],encoding='utf-8').strip()==TARGET
    assert not subprocess.check_output(['git','-C',str(source),'status','--porcelain','--untracked-files=no'],encoding='utf-8').strip()
    path=source/'packages/workflow/workflow-ptc/src/guest-source.ts'
    if hashlib.sha256(path.read_bytes()).hexdigest()!='5c002a19329f7f910f42553c58a218cc83c73316ba96b23ecdcccc1e31626468':
        raise ValueError('Workflow generated Guest source differs')
    guest=json.loads(path.read_text(encoding='utf-8').split('export const WORKFLOW_GUEST_SOURCE = ',1)[1].strip().rstrip(';'))
    assets=output/'ptc-executor';assets.mkdir(parents=True)
    (output/'ptc_guest.js').write_bytes(guest.encode('utf-8'))
    (output/'PTC-GUEST-LICENSE').write_bytes((source/'LICENSE').read_bytes())
    vm=(ROOT/'scripts/native/workflow/vm.js').read_text(encoding='utf-8').replace('export class Script','class Script').replace('export function createContext','function createContext')+'\nconst vm = {Script, createContext}\n'
    (assets/'vm.js').write_bytes(vm.encode('utf-8'))
    for name,path in [('error-stack.js',ROOT/'dsh/javascript/workflow/error-stack.js'),('driver.js',ROOT/'scripts/native/workflow-ptc/driver.js')]:
        (assets/name).write_bytes(path.read_bytes())
    resources={str(path.relative_to(output)).replace('\\','/'):hashlib.sha256(path.read_bytes()).hexdigest() for path in [output/'ptc_guest.js',assets/'vm.js',assets/'driver.js',assets/'error-stack.js']}
    receipt=dict(upstream=TARGET,adaptation='Only ESM import/export envelope removed in memory; node:vm delegated to the previously qualified native private-realm adapter. Carrier exposes only five Workflow Host RPC functions.',resources=resources)
    (assets/'resources.json').write_text(json.dumps(receipt,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(output=str(output),resources=resources,manifest_sha256=hashlib.sha256((assets/'resources.json').read_bytes()).hexdigest())))


if __name__=='__main__':main()
