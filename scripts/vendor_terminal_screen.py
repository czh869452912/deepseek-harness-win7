"""Copy unchanged pinned xterm artifacts for the existing Win7 QuickJS substrate."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parents[1]
TARGET='38a6a5c965aa99ab525161efb7cc5cf1fe62fced'
XTERM='f447274f430fd22513f6adbf9862d19524471c04'
LICENSE_SHA='b569f629d00f2626a8100df2a1798210535621e42164dfd426a6fe5aac7b0ccd'


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--source',type=Path,required=True);parser.add_argument('--license',type=Path,required=True);args=parser.parse_args()
    source=args.source.resolve()
    if subprocess.check_output(['git','rev-parse','HEAD'],cwd=str(source)).decode().strip()!=TARGET:raise ValueError('Source target differs')
    if subprocess.check_output(['git','status','--porcelain','--untracked-files=no'],cwd=str(source)):raise ValueError('Source tracked files differ')
    output=ROOT/'dsh/javascript/terminal-screen';output.mkdir(exist_ok=True)
    packages=source/'packages/api/terminal-controller/node_modules/@xterm';inputs=[]
    for name,version,artifact,destination in [('headless','6.0.0','lib-headless/xterm-headless.js','headless.js'),('addon-serialize','0.14.0','lib/addon-serialize.js','serialize.js')]:
        package=json.loads((packages/name/'package.json').read_text(encoding='utf-8'))
        if package['version']!=version or package['commit']!=XTERM:raise ValueError('xterm dependency identity differs')
        data=(packages/name/artifact).read_bytes();(output/destination).write_bytes(data)
        inputs.append(dict(package='@xterm/'+name,version=version,commit=XTERM,artifact=artifact,bytes=len(data),sha256=hashlib.sha256(data).hexdigest()))
    license_data=args.license.read_bytes()
    if hashlib.sha256(license_data).hexdigest()!=LICENSE_SHA:raise ValueError('xterm license identity differs')
    (output/'XTERM-LICENSE.txt').write_bytes(license_data)
    manifest=dict(source_commit=TARGET,xterm_commit=XTERM,license_url='https://raw.githubusercontent.com/xtermjs/xterm.js/'+XTERM+'/LICENSE',
        inputs=inputs,resources={path.name:dict(bytes=len(path.read_bytes()),sha256=hashlib.sha256(path.read_bytes()).hexdigest())
            for path in (output/'headless.js',output/'serialize.js',output/'XTERM-LICENSE.txt',output/'driver.js')})
    data=(json.dumps(manifest,indent=2)+'\n').encode('utf-8');(output/'manifest.json').write_bytes(data)
    print('manifest_sha256='+hashlib.sha256(data).hexdigest());print(json.dumps(manifest,indent=2))


if __name__=='__main__':main()
