"""Immutable config references, schema paths and raw comparison contracts."""
import datetime

import pytest

from dsh.cordis import Schema as z, ValidationError
from dsh.cordis.loader_diff import equal_except_volatile
from dsh.cordis.utils import _UNDEFINED, deep_equal
from dsh.cordis.volatile import create_volatile, is_volatile, update_volatile, volatile_entries


def config():
    return z.object({'fixed':z.string().default('fixed'),'title':z.string().default('hello').volatile(),
        'optional':z.string().volatile(),'nested':z.object({'count':z.number().min(0).volatile().default(1)}).default({}),
        'group':z.object({'list':z.array(z.string())}).default({'list':[]}).volatile()})


def test_schema_references_defaults_absence_simplification_and_roundtrip():
    schema=config();parsed=schema({})
    assert parsed['title'].get()=='hello'
    assert parsed['optional'].get() is _UNDEFINED
    assert parsed['nested']['count'].get()==1
    assert schema.simplify(parsed) is None
    restored=z(schema.toJSON());other=restored({'title':'changed'})
    assert restored.simplify(other)=={'title':'changed'}
    assert schema({'nested':{'count':-1}}, {'autofix':True})['nested']['count'].get()==1
    with pytest.raises(ValidationError):schema({'nested':{'count':-1}})


def test_snapshots_are_detached_immutable_and_old_reads_survive_commit():
    original={'list':['a']};reference=create_volatile(original);old=reference.get();original['list'].append('b')
    assert old=={'list':['a']}
    with pytest.raises(TypeError):old['list'].append('c')
    with pytest.raises(TypeError):old['key']=1
    with pytest.raises(TypeError):reference.get=lambda:None
    candidate=create_volatile({'list':['new']});update_volatile(reference,candidate)
    assert reference.get() is candidate.get() and old=={'list':['a']}


@pytest.mark.parametrize('value,message',[(lambda:None,'functions'),(datetime.datetime(2026,1,1),'plain objects')])
def test_unsupported_snapshot_values_are_rejected(value,message):
    with pytest.raises(TypeError,match=message):create_volatile(value)
    schema=z.object({'value':z.any().volatile()})
    with pytest.raises(ValidationError,match='value'):schema({'value':value})


def test_cycles_are_rejected_but_shared_values_visit_each_path():
    cyclic={};cyclic['self']=cyclic
    with pytest.raises(TypeError,match='cycles'):create_volatile(cyclic)
    ref=create_volatile({'nested':1});shared={'live':ref};container={'list':[shared,shared]};container['self']=container
    assert volatile_entries(container)==[{'path':['list','0','live'],'ref':ref},{'path':['list','1','live'],'ref':ref}]
    assert volatile_entries(ref)==[{'path':[],'ref':ref}]


@pytest.mark.parametrize('schema',[
    lambda:z.object({'items':z.array(z.string().volatile())}),
    lambda:z.object({'items':z.dict(z.string().volatile())}),
    lambda:z.union([z.object({'title':z.string().volatile()}),z.string()]),
    lambda:z.object({'items':z.tuple([z.string().volatile()])}),
    lambda:z.intersect([z.object({'title':z.string().volatile()})]),
    lambda:z.transform(z.object({'title':z.string().volatile()}),lambda value:value),
    lambda:z.object({'block':z.object({'title':z.string().volatile()}).volatile()}),
])
def test_volatile_requires_fixed_object_path_even_when_absent(schema):
    with pytest.raises(ValidationError,match='fixed object path'):schema()({})


def test_whole_array_union_repeat_and_lazy_paths():
    with pytest.raises(TypeError,match='already wrapped'):z.string().volatile().volatile()
    assert z.array(z.string()).volatile()(['a']).get()==['a']
    assert z.union([z.string(),z.number()]).volatile()(1).get()==1
    with pytest.raises(ValidationError,match='lazy'):
        z.object({'lazy':z.lazy(lambda:z.object({'live':z.string().volatile()}))})({'lazy':{'live':'value'}})


def test_metadata_free_serialized_schema_nodes_are_checked():
    schema=z({'type':'object','dict':{'enabled':{'type':'boolean'}}})
    assert schema({'enabled':True})=={'enabled':True}
    invalid=z({'type':'object','dict':{'items':{'type':'array','inner':{'type':'string','meta':{'volatile':True}}}}})
    with pytest.raises(ValidationError,match='items'):invalid({'items':[]})


def test_comparison_is_strict_through_arrays_and_opaque_cycles():
    assert deep_equal(create_volatile(1),create_volatile(2),True)
    assert not deep_equal(create_volatile(1),1,True)
    assert not deep_equal([_UNDEFINED],[None],True)
    assert deep_equal([_UNDEFINED],[None])
    left={};left['self']=left;right={};right['self']=right
    assert not deep_equal(left,right,True)
    assert deep_equal(left,left,True)
    class Opaque:pass
    assert not deep_equal(Opaque(),Opaque(),True)
    assert deep_equal(Opaque(),Opaque())


def test_frozen_json_objects_keep_plain_data_comparison_and_snapshot_protocol():
    from dsh.core.session.json import FrozenDict, FrozenList
    frozen=FrozenDict({'list':FrozenList(['a'])})
    assert deep_equal(frozen,{'list':['a']},True)
    assert create_volatile(frozen).get()=={'list':['a']}
    schema=z.object({'live':z.string().volatile()})
    assert equal_except_volatile(FrozenDict({'live':'old'}),FrozenDict({'live':'new'}),schema)


def test_raw_diff_ignores_only_volatile_fixed_paths_without_resolving():
    calls=[]
    schema=z.object({'nested':z.object({'live':z.string().volatile(),'fixed':z.string()}).default({'fixed':'default'}),
                     'transform':z.transform(z.string(),lambda value:calls.append(value))})
    assert equal_except_volatile({}, {'nested':{'live':{'__jsExpr':'throw 1'},'fixed':'default'}}, schema)
    assert not equal_except_volatile({}, {'nested':{'live':'new'}}, schema)
    assert not equal_except_volatile({'nested':{'__jsExpr':'a'}},{'nested':{'__jsExpr':'b'}},schema)
    assert not equal_except_volatile({'transform':'first'},{'transform':'second'},schema)
    assert calls==[]
    for key in ('constructor','toString','__proto__'):
        assert not equal_except_volatile({key:'old'},{key:'new'},schema)
