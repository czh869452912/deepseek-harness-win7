"""Reproduce the normalized plugin-market tool descriptor from fixed Source."""
import argparse
import json
from pathlib import Path
import subprocess
ROOT=Path(__file__).resolve().parents[1]
TARGET='38a6a5c965aa99ab525161efb7cc5cf1fe62fced'

def prepare(source,node):
    assert subprocess.check_output(['git','-C',str(source),'rev-parse','HEAD'],encoding='utf-8').strip()==TARGET
    assert not subprocess.check_output(['git','-C',str(source),'status','--porcelain','--untracked-files=no'],encoding='utf-8').strip()
    raw=subprocess.check_output([str(node),str(source/'node_modules/tsx/dist/cli.mjs'),'--tsconfig',str(source/'tsconfig.base.json'),str(ROOT/'scripts/oracles/rc022_market_definition.mts'),str(source)])
    (ROOT/'dsh/boot/plugin_market_tools.json').write_text(json.dumps(json.loads(raw),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--source',type=Path,required=True);parser.add_argument('--node',type=Path,required=True)
    args=parser.parse_args();prepare(args.source.resolve(),args.node.resolve())
