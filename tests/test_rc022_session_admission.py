import copy

import pytest

from scripts.rc022_session_admission_probe import cases, native_row, projection_rows


@pytest.mark.parametrize('row',[row for row in cases() if row['name'].endswith('-valid')],ids=lambda row:row['name'])
def test_v4_identified_messages_restore_and_enter_surface(row):
    result=native_row(row)
    assert 'error' not in result
    assert result['nodes']==[0] and result['seq']==2


def test_known_message_interpreter_is_required_even_for_empty_payload():
    row=next(row for row in cases() if row['name']=='missing-projection')
    assert 'requires a message projection' in native_row(row)['error']


def test_v4_tool_content_rewrite_preserves_message_identity_and_metadata():
    rows=[native_row(row) for row in cases() if row['name'].startswith('tool-rewrite-')]
    assert 'error' not in rows[0] and rows[0]['nodes']==[1]
    assert 'may change only content' in rows[1]['error']
    assert 'may change only content' in rows[2]['error']
    assert 'mismatched tool call ids' in rows[3]['error']


def test_v4_adoption_freezes_developer_message_and_detaches_snapshot():
    from dsh.core.session.current import adoptSessionEvent, snapshotSessionEvent
    row=next(row for row in cases() if row['name']=='developer/message-valid')
    event=copy.deepcopy(row['events'][0]);event['data']['extension']={}
    snapshot=snapshotSessionEvent(event,4)
    assert snapshot is not event and snapshot['data']['message'] is not event['data']['message']
    assert adoptSessionEvent(event,4) is event
    with pytest.raises(TypeError):event['data']['message']['role']='user'
    event['data']['extension']['allowed']=True


def test_seed_marker_accepts_json_floating_number_cut():
    row=next(row for row in cases() if row['name']=='seed-create-0-[0]')
    row=copy.deepcopy(row);row['cut']=0.0
    assert 'error' not in native_row(row)


def test_message_interpretation_cannot_outlive_the_exact_definition():
    rows={row['name']:row for row in projection_rows()}
    assert rows['projection-read']['messages']==[[dict(type='text',text='projected')]]
    assert rows['projection-read']['generation']==1 and rows['projection-read']['position']==0
    for action in ('remove','replace','remove-pending'):
        assert 'was removed or replaced' in rows['projection-'+action]['error']
    assert rows['projection-unused']['generation']==0
    assert rows['projection-uncommitted']['nodes']==[]
