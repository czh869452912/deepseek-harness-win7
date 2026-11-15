"""Generate compact Unicode 16 tables and conformance fixtures from verified inputs."""
import argparse
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
IDENTITIES={
    'GraphemeBreakProperty.txt':'c29360bd6f7132811d701d29069541e827eb44bfc4c8fbde8c370d6982689dc1',
    'GraphemeBreakTest.txt':'ee2b9354d270ac061b29f09662cafea06341d77e704b8cc6bd72aaeeda363cb5',
    'emoji-data.txt':'f1365a5173eee18e1f98b240cdc492e84a25f1ce7e0c9d1094eb29c41a22696a',
    'DerivedCoreProperties.txt':'39d35161f2954497f69e08bdb9e701493f476a3d30222de20028feda36c1dabd',
    'LICENSE.txt':'e7a93b009565cfce55919a381437ac4db883e9da2126fa28b91d12732bc53d96',
}


def generate(inputs):
    texts={};records=[]
    for name,sha in IDENTITIES.items():
        data=(inputs/name).read_bytes()
        if hashlib.sha256(data).hexdigest()!=sha:raise ValueError('Unicode input identity differs: '+name)
        relative='auxiliary/'+name if name.startswith('Grapheme') else 'emoji/'+name if name=='emoji-data.txt' else name
        url='https://www.unicode.org/license.txt' if name=='LICENSE.txt' else 'https://www.unicode.org/Public/16.0.0/ucd/'+relative
        texts[name]=data.decode('utf-8');records.append(dict(name=name,url=url,bytes=len(data),sha256=sha))
    tables={name:[] for name in ('gcb','incb','pictographic')}
    for name,table in [('GraphemeBreakProperty.txt','gcb'),('DerivedCoreProperties.txt','incb'),('emoji-data.txt','pictographic')]:
        for line in texts[name].splitlines():
            parts=[part.strip() for part in line.split('#')[0].split(';')]
            if len(parts)<2:continue
            if table=='incb' and parts[1]!='InCB':continue
            if table=='pictographic' and parts[1]!='Extended_Pictographic':continue
            prop=parts[2] if table=='incb' else parts[1]
            if table=='gcb' and prop in ('LV','LVT'):continue # Algorithmic Hangul syllables.
            bounds=[int(value,16) for value in parts[0].split('..')]
            tables[table].append([bounds[0],bounds[-1],prop])
    for table in tables.values():table.sort()
    cases=[]
    for line in texts['GraphemeBreakTest.txt'].splitlines():
        tokens=line.split('#')[0].split()
        if not tokens:continue
        segments=[];current=''
        for token in tokens:
            if token=='÷':
                if current:segments.append(current);current=''
            elif token!='×':current+=chr(int(token,16))
        cases.append(segments)
    output=ROOT/'dsh/terminal/unicode16';output.mkdir(exist_ok=True)
    fixture=ROOT/'tests/fixtures/unicode';fixture.mkdir(parents=True,exist_ok=True)
    (output/'grapheme.json').write_text(json.dumps(tables,separators=(',',':')),encoding='utf-8')
    (output/'LICENSE.txt').write_bytes((inputs/'LICENSE.txt').read_bytes())
    (fixture/'grapheme16.json').write_text(json.dumps(cases,ensure_ascii=True,separators=(',',':')),encoding='utf-8')
    manifest=dict(unicode='16.0.0',specification='https://www.unicode.org/reports/tr29/tr29-45.html',
        input_base='https://www.unicode.org/Public/16.0.0/ucd/',inputs=records,
        generator='scripts/generate_grapheme_data.py',conformance_cases=len(cases),
        outputs={str(path.relative_to(ROOT)).replace('\\','/'):dict(bytes=len(path.read_bytes()),sha256=hashlib.sha256(path.read_bytes()).hexdigest())
                 for path in (output/'grapheme.json',output/'LICENSE.txt',fixture/'grapheme16.json')})
    (output/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(manifest,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('inputs',type=Path);generate(parser.parse_args().inputs)
