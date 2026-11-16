"""Registry plan isolation, failure attribution and published-version facts."""
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe


def corpus():
    official='https://registry.npmjs.org/'
    mirror='https://registry.npmmirror.com/'
    private='https://corp.example/'
    urls=['https://REGISTRY.npmjs.org','http://Corp.example:4873/prefix','https://USER:secret@EXAMPLE.COM:443/a?x=1#part',
          'https://example.com/a/../b','https://example.com/a/%2e%2E/b','https://example.com/a//b',
          'HTTPS:example.com/path','https:\\example.com\\a','https://example.com/a b',
          'https://example.com/\u4e2d\u6587?q=\u6587','http://127.1','http://[::1]:80/p','https://[bad]',
          'https://host:99999','https://','ftp://example.com','', 'example.com',
          ' https://Host/p\tath\r\n ','https://host/?','https://host/#','https://a@b@host/p',
          'https://host/%2E','https://host/a/..','https://host/a/../../b', 'https://host/a\\b?x=\\y']
    plans=[]
    for own in (official,mirror,private,None):
        for first,fallback in [(None,[mirror]),(mirror,[mirror,private]),(private,[mirror]),(None,[mirror,mirror,official])]:
            for requested in ('absent',None,mirror,private,official):
                item=dict(configured=dict(registry=first,fallbackRegistries=fallback,resolved=own))
                if requested!='absent':item['requested']=requested
                plans.append(item)
    failures=[]
    for spec in ('pkg','github:a/b','https://cdn.example/a.tgz'):
        for kind in ('network','timeout','not-found','no-matching-version','build-blocked','permission','unknown'):
            for log in ('WARN see https://github.com/a/b\nERR_PNPM_FETCH_FAIL registry.npmjs.org',
                        'fatal: unable to access GITHUB.COM','ERR_PNPM_FETCH_502 cdn.example',
                        'ECONNRESET','error\u4e2d github.com','Error github.com'):
                failures.append(dict(spec=spec,kind=kind,log=log))
    versions=[dict(answer=value,installed=installed) for value in [None,[],{},dict(versions='2.0.0'),
        dict(versions=['1.0.0','1.2.0','v2.0.0','2.0.0-beta.2','2.0.0-beta.10','2.0.0+build','2.0.0','broken',3,None,True],
             time={'v2.0.0':'date','1.2.0':9},**{'dist-tags':{'latest':'2.0.0','next':'2.0.0-beta.10','2':'2.0.0','1':'2.0.0'}}),
        dict(versions=[' 2.0.0 ','2.0.0-01','1.02.0','2.0.0','2.0.0'],time='bad',**{'dist-tags':[]})]
        for installed in ('1.0.0','2.0.0-beta.1','bad')]
    facts=[None,[],{},'scalar',dict(name='x',version='2.0.0',engines=None,peerDependencies=False,dsh=dict(bundle={})),
           dict(name=3,version=None,deprecated='',dsh=dict(bundle=[])),dict(deprecated='old',dsh=dict(bundle=dict(patch='p')))]
    return dict(urls=urls,plans=plans,failures=failures,versions=versions,facts=facts)


def result(operation):
    try:return dict(value=operation())
    except Exception:return dict(error=True)


async def observe():
    from dsh.boot.plugin_registry_policy import normalize_registry,registry_plan,attribute_failure,newer_versions,version_facts,UNSPECIFIED
    from dsh.boot.plugin_install_spec import parse_install_spec
    data=corpus();rows=[]
    for url in data['urls']:rows.append(dict(kind='url',input=url,result=result(lambda:normalize_registry(url))))
    for item in data['plans']:rows.append(dict(kind='plan',input=item,result=result(lambda:registry_plan(item.get('requested',UNSPECIFIED),item['configured']))))
    for item in data['failures']:rows.append(dict(kind='failure',input=item,value=attribute_failure(item['kind'],item['log'],parse_install_spec(item['spec']))))
    for item in data['versions']:rows.append(dict(kind='versions',input=item,result=result(lambda:newer_versions(item['answer'],item['installed']))))
    for item in data['facts']:rows.append(dict(kind='facts',input=item,value=version_facts(item,'fallback','1.0.0')))
    return rows


def prepare(output):
    path=output/'input.json';path.write_text(json.dumps(corpus()),encoding='utf-8');return [path]


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_registry_policy.mts','Registry URL comparison, private/unknown registry retry isolation and deduplication, failure host attribution from error lines only, published version semver filtering/order/tags and manifest facts. Compare error presence only.',[Path(__file__).resolve(),ROOT/'dsh/boot/plugin_registry_policy.py'],prepare=prepare)
