"""Journal persistence boundaries: pending deltas survive until their owner saves."""
import copy
from types import SimpleNamespace

from dsh.cordis import include_journal as j
from dsh.cordis.include_patch import PatchIndex, ensure_insert_ids, route_journal
from dsh.cordis.utils import _UNDEFINED


def upsert(changes, parent=_UNDEFINED, created=False, position=0):
    return dict(kind='upsert', created=created, parent=parent, position=position, changes=changes)


def test_report_uses_current_identity_and_shallow_delta_before_live_tree_changes():
    legacy={'id':'a','disabled':True,'config':{'value':1}}
    options={'id':'a','config':{'value':2}}
    pending={};j.record(pending,dict(id='a',group=SimpleNamespace(data=[{},options]),legacy=legacy,options=options),'g')
    assert pending['a']==upsert({'disabled':_UNDEFINED,'config':{'value':2}},position=1)
    options['config']={'value':3}
    assert pending['a']['changes']['config']=={'value':2}
    j.merge(pending,'a',upsert({'config':{'value':4}},parent='other',position=3))
    assert pending['a']==upsert({'disabled':_UNDEFINED,'config':{'value':4}},parent='other',position=3)


def test_created_then_removed_cancels_but_recreated_existing_entry_is_not_new():
    pending={};j.merge(pending,'a',upsert({'name':'new'},created=True,parent=None))
    j.merge(pending,'a',{'kind':'remove'});assert pending=={}
    j.merge(pending,'a',{'kind':'remove'});j.merge(pending,'a',upsert({'name':'replacement'},created=True,parent=None))
    assert pending['a']['created'] is False


def test_failed_relocation_restores_old_position_after_applying_field_delta():
    data=[{'id':'before'},{'id':'a','config':1},{'id':'after'}];warnings=[]
    j.apply_journal(data,{'a':upsert({'config':2},parent='missing')},warn=lambda *args:warnings.append(args))
    assert [row['id'] for row in data]==['before','a','after']
    assert data[1]['config']==2 and warnings==[('cannot move entry %C: group %C not found','a','missing')]


def test_external_file_wins_only_conflicting_fields_and_moves():
    base=[{'id':'g','group':True,'config':[{'id':'a','config':1,'disabled':False}]},
          {'id':'h','group':True,'config':[]}]
    theirs=[{'id':'g','group':True,'config':[]},
            {'id':'h','group':True,'config':[{'id':'a','config':3,'disabled':False}]}]
    pending={'a':upsert({'config':2,'disabled':True},parent=None)}
    conflicts=j.reconcile(pending,j.flatten(base),j.flatten(theirs),lambda entry_id,key:True)
    assert conflicts==[{'id':'a','reason':'key "config" modified both in file and at runtime'},
                       {'id':'a','reason':'moved both in file and at runtime'}]
    assert pending=={'a':upsert({'disabled':True})}
    j.apply_journal(theirs,pending)
    assert theirs[1]['config'][0]=={'id':'a','config':3,'disabled':True}


def test_patch_owners_route_deletion_overrides_and_new_children_without_file_leak():
    data=[{'id':'a','name':'example','disabled':False}]
    patches=[{'id':'a','disabled':True},{'id':'a','disabled':False},
             {'insert':[{'id':'g','group':True,'config':[{'id':'b','name':'child'}]}]}]
    pending={'a':upsert({'disabled':_UNDEFINED,'config':2}),
             'b':{'kind':'remove'},'c':upsert({'name':'new'},parent='g',created=True)}
    assert route_journal(pending,data,patches)
    assert data==[{'id':'a','name':'example','disabled':False,'config':2}]
    assert patches[0]['disabled'] is True and 'disabled' not in patches[1]
    assert patches[2]['insert'][0]['config']==[{'id':'c','name':'new'}]
    index=PatchIndex(patches)
    assert index.key('a','disabled')=={'type':'patch','index':0}
    assert not index.file_owned('c',None) and index.file_owned('a','config')


def test_journal_reconciliation_skips_inserted_entries_and_patch_owned_fields():
    pending={'a':upsert({'disabled':True,'config':2}), 'b':upsert({'config':4})}
    base=[{'id':'a','disabled':False,'config':1}];theirs=[{'id':'a','disabled':None,'config':3}]
    index=PatchIndex([{'id':'a','disabled':False},{'insert':[{'id':'b','config':1}]}])
    conflicts=j.reconcile(pending,j.flatten(base),j.flatten(theirs),index.file_owned)
    assert conflicts==[{'id':'a','reason':'key "config" modified both in file and at runtime'}]
    assert pending['a']['changes']=={'disabled':True} and pending['b']['changes']=={'config':4}


def test_generated_insert_ids_are_recursive_stable_and_collision_checked():
    patches=[{'insert':[{'group':True,'config':[{'name':'child'}]}]}]
    ensure_insert_ids(patches,lambda entry_id:False)
    first=copy.deepcopy(patches)
    ensure_insert_ids(patches,lambda entry_id:True)
    assert patches==first
    assert len(patches[0]['insert'][0]['id'])==8
    assert len(patches[0]['insert'][0]['config'][0]['id'])==8
