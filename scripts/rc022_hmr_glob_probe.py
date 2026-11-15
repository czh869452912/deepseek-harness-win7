"""Compare ignore-pattern decisions against the pinned picomatch dependency."""
import asyncio
import itertools
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
OUTPUT=None
PATTERNS=['@(foo|bar)','+(foo|bar)','?(foo|bar)','*(foo|bar)','!(foo|bar)','!(foo|bar).js','**/!(foo).js','a+(b|c).js','@(foo|bar)/**','+(foo|@(bar|baz))','{1..4}.txt','{a..d}.js','{01..03}.js','{1..4..2}.txt','{a,{b,c}}.js','**/*.{js,ts}','[[:digit:]].txt','[[:alpha:]]*','[[:alnum:]]*','[[:upper:]]*','[[:lower:]]*','[[:space:]]','[[:xdigit:]]*','!!foo','!!!foo','[abc','a{b','a(b|c)','foo/','foo','foo/**','**','*','**/*.js','**/.*','**/+(foo|bar).js','foo/!(bar)/**','foo/**/bar','[!a].txt','[^a].txt','[a-c].txt','[a-c].txt/','./@(foo|bar)','a\\*.js']
PATHS=['','.','..','.foo','foo','bar','baz','foobar','barfoo','foobarbaz','foo.js','bar.js','baz.js','foofoo.js','fooa.js','.foo.js','foo/bar','foo/bar.js','foo/baz.js','foo/.x','foo/.x/bar','foo/bar/baz','foo/baz/bar','foo/','bar/','a','b','c','d','1','2','A','f',' ','a.txt','b.txt','c.txt','d.txt','1.txt','2.txt','3.txt','4.txt','5.txt','01.js','02.js','03.js','a.js','b.js','c.js','d.js','ab.js','ac.js','abbc.js','a(b|c)','[abc','a{b','x.ts','foo/x.ts','foo\\bar.js','a*.js']
PATTERNS += [prefix+op+'('+alternatives+')'+suffix
             for prefix,op,alternatives,suffix in itertools.product(
                 ('','a','**/','foo/'), ('@','+','?','*','!'),
                 ('foo|bar','a|b','f*|b?','foo|@(bar|baz)'), ('','.js','/**'))]
PATHS += [prefix+name+suffix for prefix,name,suffix in itertools.product(
    ('','foo/','bar/','.hidden/'), ('a','b','foo','bar','baz','foobar','aa','ab','foofoo','.foo'), ('','.js','/','/x','/bar'))]
PATTERNS += ['[[:'+name+':]]' for name in ('alnum','alpha','ascii','blank','cntrl','digit','graph','lower','print','punct','space','upper','word','xdigit')]
PATHS += [chr(value) for value in range(1,128)]
PATTERNS = list(dict.fromkeys(PATTERNS))
PATHS = list(dict.fromkeys(PATHS))
def prepare(output):
 global OUTPUT
 OUTPUT=output
 p=output/'input.json';p.write_text(json.dumps(dict(patterns=PATTERNS,paths=PATHS)),encoding='utf-8');return [p]
async def native():
 from dsh.cordis.hmr_glob import matches
 return [dict(pattern=p,values=[matches(path,[p]) for path in PATHS]) for p in PATTERNS]
if __name__=='__main__':
 probe.native=native
 probe.main('rc022_hmr_glob.mts','Pinned picomatch ignore decisions: nested extglobs, ranges, nested braces, POSIX classes, repeated negation, dot and native separators.',[Path(__file__).resolve(),ROOT/'dsh/cordis/hmr_glob.py', *[ROOT/'.goose/out/rc022-prep-20261114-01/source/packages/boot/hmr/node_modules/picomatch/lib'/name for name in ('parse.js','scan.js','constants.js','picomatch.js')]],prepare,plain_node=True)
