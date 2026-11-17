import errno
import os

import pytest

from dsh.typert.dispatch import original_of
from scripts.rc022_workspace_membership_probe import observe
from tests.test_rc022_workspace_default import host


@pytest.mark.asyncio
async def test_actual_json_missing_candidates_reindex_and_cold_reopen(tmp_path):
    rows=await observe(tmp_path);assert len(rows)==16
    by_name={row['step']:row for row in rows}
    assert by_name['missing-reopen']['ids']==['second','first']
    assert by_name['missing-manual-order']['stored']==['first','second']
    assert 'does not resolve' in by_name['missing-new-attach']['error']['message']
    assert by_name['fresh-header-moves-first']['ids']==['second']
    assert by_name['fresh-header-missing-again']['ids']==['first','second']
    assert by_name['write-prunes-invalid']['stored']==['second']
    assert by_name['restore-reattach']['ids']==['second']
    assert by_name['absent-header-cold-reopen']['ids']==[]
    assert by_name['write-prunes-absent']['stored']==[]
    assert by_name['missing-never-bootstraps']['workspaces']==0


@pytest.mark.asyncio
@pytest.mark.parametrize('code',[errno.ENOENT,errno.EACCES,errno.ELOOP,errno.ENOTDIR])
async def test_only_enoent_preserves_accounted_candidates(host,tmp_path,monkeypatch,code):
    entity=await host.registry.create(str(tmp_path));header=dict(id='held',cwd=str(tmp_path))
    host.headers.append(dict(header=header));await entity.attachSession('held')
    registry=original_of(host.registry)
    def fail(_):raise OSError(code,'selected path failure')
    monkeypatch.setattr(registry,'_normalize_path',fail)
    await registry._index_headers([header])
    assert entity.sessionIds==(['held'] if code==errno.ENOENT else [])
    await entity.setTitle('Validated')
    assert registry._table.get(entity.id)['sessionIds']==entity.sessionIds


@pytest.mark.asyncio
async def test_stat_enoent_after_realpath_keeps_owned_slot(host,tmp_path,monkeypatch):
    entity=await host.registry.create(str(tmp_path));header=dict(id='held',cwd=str(tmp_path))
    host.headers.append(dict(header=header));await entity.attachSession('held')
    registry=original_of(host.registry);monkeypatch.setattr(registry,'_normalize_path',lambda _:str(tmp_path))
    real_stat=os.stat
    def stat(path,*args,**kwargs):
        if path==str(tmp_path):raise FileNotFoundError(errno.ENOENT,'removed between realpath and stat')
        return real_stat(path,*args,**kwargs)
    with monkeypatch.context() as scope:
        scope.setattr(os,'stat',stat);await registry._index_headers([header])
    assert entity.sessionIds==['held']


@pytest.mark.asyncio
async def test_full_replacement_clears_absent_headers_but_append_preserves_cached_facts(host,tmp_path):
    entity=await host.registry.create(str(tmp_path));header=dict(id='held',cwd=str(tmp_path))
    host.headers.append(dict(header=header));await entity.attachSession('held')
    registry=original_of(host.registry)
    await registry._index_headers([]);assert entity.sessionIds==['held']
    await registry._replace_header_index([]);assert entity.sessionIds==[]
    assert not registry._headers and not registry._session_paths and not registry._invalid_session_paths
    assert not registry._missing_session_paths
    await entity.setTitle('Pruned');assert registry._table.get(entity.id)['sessionIds']==[]


@pytest.mark.asyncio
@pytest.mark.parametrize('kind',['no-cwd','relative','file','elsewhere'])
async def test_attach_rejects_invalid_new_cwd_without_registering_candidate(host,tmp_path,kind):
    project=tmp_path/'project';project.mkdir();entity=await host.registry.create(str(project))
    other=tmp_path/'other';other.mkdir();file=tmp_path/'file';file.write_text('keep',encoding='utf-8')
    paths=dict(relative='relative',file=str(file),elsewhere=str(other))
    host.headers.append(dict(header=dict(id='new',**({} if kind=='no-cwd' else dict(cwd=paths[kind])))))
    with pytest.raises(ValueError,match={'no-cwd':'carries no cwd','relative':'does not resolve','file':'is not a directory','elsewhere':'cwd resolves'}[kind]):
        await entity.attachSession('new')
    assert entity.sessionIds==[] and host.registry._table.get(entity.id)['sessionIds']==[]


@pytest.mark.asyncio
@pytest.mark.parametrize('operation',['create','delete'])
async def test_inconsistent_pending_order_reports_operation(host,tmp_path,operation):
    entity=await host.registry.create(str(tmp_path));registry=host.registry
    await registry._set_state(dict(registry._state,pendingMutation=dict(operation=operation,workspaceId=entity.id)))
    with pytest.raises(ValueError,match='pending '+operation+' workspace'):
        await registry.pinSession('missing')
