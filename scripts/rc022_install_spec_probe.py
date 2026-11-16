"""Pinned package install identities and diagnostic classification."""
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe


def corpus():
    commit='0123456789abcdef'*2+'01234567'
    specs=['',' ','\ufeff pkg@latest \u00a0','pkg','pkg@','@scope/pkg@^1.2','pkg@npm:another@1','pkg@tag with spaces','Dsh-Upper','.hidden','_hidden','has space','a'*214,'a'*215,'@a/b','@a/','@A/b','p~g','pkg\x85','file:relative','link:../package','FILE:/plugins/x','./x','../x','.','..','/plugins/x','file:/plugins/x','link:C:\\plugins\\x','C:\\packs\\x.tgz','C:relative','\\server\\share\\plugin','/packs/x.tar.gz#x','https://example.com/not-a-package','https://cdn.example.com/a/b/c.tgz','https://Host:443/a/b','https://Host:443/a/b.git#main','https://user:secret@Host:8443/a/b.git','https://0x7f.1/a/b','https://[::1]:443/a/b','https://[bad]/a/b','https://Host:99999/a/b','git://HOST/a/b','git+ssh://git@HOST:2222/a/b.git','git@HOST:a/b.git','github:a/b','gitlab:a/b#main','bitbucket:a/b','gist:abcdef','github:a/b.tgz','https://host/a/b.tgz?query=1','https://host/a/b.tgz#fragment','https://host/a/b.tgz#x\u2028y']
    specs += ['git://HOST:00080/a/b', 'git://HOST:/a/b', 'git://[0:0:0:0:0:0:0:1]:00080/a/b', 'git+ssh://HOST:00022/a/b']
    bases=['github:a/b','gitlab:a/b.git','git@HOST:a/b.git','git+https://user:secret@HOST:8443/a/b.git','https://Host/a/b.git','git+ssh://user@HOST/a/b.git']
    specs += [base+'#'+fragment for base in bases for fragment in [commit,commit.upper(),commit[:7],commit+'&path:/packages/foo/', 'path:foo&'+commit,commit+'&path:one&path:two',commit+'&'+commit,'path:one',commit+'&path:']]
    dependencies=[]
    dependencies += [dict(name='pkg',recorded=saved,profile='C:/profiles/test',packageName='pkg') for saved in ('git@\ufeffhost:path', 'git@\x85host:path')]
    for name in ('pkg','alias'):
        for saved in ('^1.2','latest','npm:other@1','jsr:other@1','workspace:*','catalog:tools','git+https://name:secret@Host/a/b.git?token=query#commit','https://name:secret@Host/a/b.tgz?token=query','git@host:a/b.git','file:../local','link:~/local','file:C:/absolute/plugin','file:relative.tgz','github:a/b#main'):
            dependencies.append(dict(name=name,recorded=saved,profile='C:/profiles/test',packageName='pkg'))
    logs=['','unrecognized','ERR_PNPM_IGNORED_BUILDS','Ignored build scripts: package','ERR_PNPM_GIT_DEP_PREPARE_NOT_ALLOWED','ERR_PNPM_FETCH_404','E404','xE404y','404 Not Found','Not Found - GET','ERR_PNPM_NO_MATCHING_VERSION','ETARGET','No matching version','ENOSPC','no space left on device','EACCES','EPERM','permission denied','ERR_PNPM_TARBALL_INTEGRITY','ERR_PNPM_BAD_TARBALL_SIZE','EINTEGRITY','ENOTFOUND','ECONNRESET','ETIMEDOUT','ECONNREFUSED','EAI_AGAIN','ERR_PNPM_META_FETCH_FAIL','ERR_PNPM_FETCH_502','ERR_PNPM_FETCH_TIMEOUT','FETCH_ERROR','socket hang up','Could not resolve host','unable to access','ERR_PNPM_NO_OFFLINE_META','fetch_error','Error \u4e2dENOSPC\u6587']
    logs += ['fatal: unable to access: The requested URL returned error: '+str(code) for code in (401,403,404,500)]
    failures=[dict(log=log) for log in logs]
    failures += [dict(log='ENOSPC ECONNRESET ERR_PNPM_IGNORED_BUILDS',timedOut=flag,cause=dict(code=code)) for flag in (True,False,1) for code in ('ENOENT','OTHER')]
    failures += [dict(log=first+' '+second) for first in ('ENOSPC','E404','ETARGET','EINTEGRITY','EACCES') for second in ('ECONNRESET','ERR_PNPM_IGNORED_BUILDS')]
    return dict(specs=specs,dependencies=dependencies,failures=failures)


def result(operation):
    try:return dict(value=operation())
    except Exception as error:
        fields=dict(name=getattr(error,'name',error.__class__.__name__),message=getattr(error,'message',str(error)))
        for key in ('spec','reason'):
            if hasattr(error,key):fields[key]=getattr(error,key)
        return dict(error=fields)


async def observe():
    from dsh.boot.plugin_install_spec import parse_install_spec,pinned_git_origin,dependency_spec,classify_install_failure
    data=corpus();rows=[]
    for spec in data['specs']:rows.append(dict(kind='spec',input=spec,parsed=result(lambda:parse_install_spec(spec)),origin=result(lambda:pinned_git_origin(spec))))
    for item in data['dependencies']:rows.append(dict(kind='dependency',input=item,value=dependency_spec(item['name'],item['recorded'],item['profile'],item['packageName'])))
    for item in data['failures']:rows.append(dict(kind='failure',input=item,value=classify_install_failure(item)))
    return rows


def prepare(output):
    path=output/'input.json';path.write_text(json.dumps(corpus()),encoding='utf-8');return [path]


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_install_spec.mts','Actual install-spec and failure classifiers: exact registry/path/tarball/Git parsing and refusals, normalized fixed-commit identities including subdirectory parameters and repeat rejection, saved dependency reinstallation specs and HTTP user-info removal, stable error-kind precedence and end-of-run facts.',[Path(__file__).resolve(),ROOT/'dsh/boot/plugin_install_spec.py'],prepare=prepare)
