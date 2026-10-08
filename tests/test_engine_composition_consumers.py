import copy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

import zipfile
from scripts import engine_composition_values as comparison

ROOT=Path(__file__).resolve().parents[1]
ARCHIVE=ROOT/'migration/evidence/artifacts/HANDOFF-COMPOSITION-QUALIFICATION-20261009-5961F1AB.zip'

@pytest.fixture(scope='module')
def actual_pair():
    assert hashlib.sha256(ARCHIVE.read_bytes()).hexdigest()=='a8e3c3e660fb82356b930e69c7ca7fc0bc8b2d50c9119ee5aa080da22a696db4'
    with zipfile.ZipFile(str(ARCHIVE)) as package:
        source=json.loads(package.read('engine/source-v1.json'))
        native=json.loads(package.read('engine/native-v1.json'))
        receipt=json.loads(package.read('engine/owned-qualification-v1.json'))
    before=comparison.project(source,source['sourceRoot']+'\\')
    assert before==comparison.project(native,native['root'])
    digest=hashlib.sha256(json.dumps(before,sort_keys=True,ensure_ascii=True,separators=(',',':')).encode('utf-8')).hexdigest()
    assert receipt['status']=='matched' and receipt['cases']==3 and receipt['observationsSha256']==digest
    return before,native

def test_complete_actual_compositions(actual_pair):
    before,_=actual_pair
    assert [len(row['public']['requests']) for row in before]==[3,2,4]
    assert [len(row['public']['created']) for row in before]==[2,2,3]
    assert [len(row['public']['disposed']) for row in before]==[1,1,2]

@pytest.mark.parametrize('damage',['model','request-presence','request-order','event-order','unknown-child','disposed','cancel','ralph-result'])
def test_real_composition_consumer_rejects_changed_values(actual_pair,damage):
    before,native=actual_pair
    broken=copy.deepcopy(native)
    first=broken['rows'][0]['public']
    if damage=='model':
        first['requests'][1]['request']['model']='wrong-child-model'
    elif damage=='request-presence':
        del first['requests'][1]['signalPresent']
    elif damage=='request-order':
        first['requests'][0],first['requests'][1]=first['requests'][1],first['requests'][0]
    elif damage=='event-order':
        first['events'][-1],first['events'][-2]=first['events'][-2],first['events'][-1]
    elif damage=='unknown-child':
        first['events'][0]['sessionId']='ffffffff-ffff-4fff-8fff-ffffffffffff'
    elif damage=='disposed':
        first['disposed']=[]
    elif damage=='cancel':
        broken['rows'][1]['public']['cancellation']=['unexpected-cancellation']
    elif damage=='ralph-result':
        event=next(row for row in reversed(broken['rows'][2]['public']['events']) if row['event']['type']=='tool/result')
        event['event']['data']['message']['content'][0]['isError']=True
    try:
        after=comparison.project(broken,broken['root'])
    except (AssertionError,KeyError,ValueError):
        return
    assert after!=before
