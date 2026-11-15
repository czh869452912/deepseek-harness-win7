from types import SimpleNamespace as NS

import pytest

from dsh.core.session.current_session import CurrentSession
from dsh.interaction.auto_review_snapshot import snapshot_auto_review, review_messages
from scripts import rc022_auto_review_snapshot_probe as probe


@pytest.mark.asyncio
async def test_authority_and_logged_native_ptc_admission():
    rows={row['name']:row['result'] for row in await probe.observe()}
    assert len(rows)==60
    for name in ('native','raw-18','child-own-prompt','ptc-valid','reused-id-other-step','json-numbers'):
        assert 'snapshot' in rows[name], rows[name]
    for name in ('duplicate-root-log','wrong-name','wrong-arguments','visible-log-mismatch','schema-bad-description',
                 'ptc-duplicate','ptc-wrong-parentCallId','ptc-nested-parent','ptc-no-owning-step','started-gap'):
        assert rows[name]['error'].startswith('auto-review: '), rows[name]
    def roles(name):
        return [item['role'] for item in rows[name]['snapshot']['history'] if item['kind']=='user-message']
    assert roles('child-own-prompt')==['direct-parent-instruction']
    assert roles('child-unverified')==['fact']
    assert roles('child-browser')==['user-instruction']
    assert roles('source-agent-instructions')==['constraint','user-instruction']
    assert roles('source-compact-checkpoint')==['checkpoint','fact','user-instruction']
    assert roles('mixed-authority')==['user-instruction','fact','user-instruction']
    assert roles('sender-parent')[0]=='direct-parent-instruction'
    assert roles('sender-stranger')[0]=='fact'


def test_actual_session_surface_snapshot_and_repeated_review_prefix():
    session=CurrentSession.create('review',format_version=4)
    schema=dict(name='probe',description='logged description',parameters=dict(type='object'))
    session.append('request/header',dict(header=dict(config=dict(provider='review',model='m'),tools=[schema]),reason='initial'))
    session.append('user/message',dict(content=[dict(type='text',text='Do task')],source=dict(kind='user')),surface_op='append')
    session.append('turn/start',dict(turn=1))
    def append_call(step):
        session.append('step/start',dict(turn=1,step=step))
        session.append('assistant/message',dict(turn=1,step=step,stream=[],message=dict(role='assistant',content=[dict(type='tool-call',id='call',name='probe',arguments='{}')],source=dict(kind='model',provider='review',model='m'))),surface_op='append')
        session.append('tool/call',dict(turn=1,step=step,callId='call',name='probe',arguments='{}'))
    append_call(1)
    agent=NS(session=session);execution=NS(name='probe',arguments={},rootCallId='call',callId='call',parent=None)
    first=snapshot_auto_review(agent,execution,'C:/work',{})
    shown={first['pending']['key']:first['pending']['schema']}
    session.append('step/end',dict(turn=1,step=1))
    session.append('user/message',dict(content=[dict(type='text',text='Loaded constraint')],source=dict(kind='agent-instructions')),surface_op='append')
    append_call(2)
    second=snapshot_auto_review(agent,execution,'C:/work',shown)
    assert review_messages(second)[:len(review_messages(first))]==review_messages(first)
    assert second['pending']['key']!=first['pending']['key']
    assert second['history'][-1]['arguments']=='{}'
    assert sum(item['kind']=='tool-schema' for item in second['history'])==1
    with pytest.raises(TypeError):
        first['pending']['schema']['description']='mutated'
    assert schema['description']=='logged description'


@pytest.mark.parametrize('raw,arguments', [('{}',{}),('',{}),('not json','not json'),('null',None)])
def test_logged_arguments_preserve_agent_loop_parsing(raw,arguments):
    case=next(c for c in probe.corpus() if c['name']=='native')
    case['events'][2]['data']['message']['content'][-1]['arguments']=raw
    case['events'][3]['data']['arguments']=raw
    case['execution']['arguments']=arguments
    session=NS(header=case['meta'],surface=NS(nodes=case['nodes']),snapshotEvents=lambda:case['events'],requestHeader=lambda:case['header'],isOwnSeq=lambda _:True)
    snapshot=snapshot_auto_review(NS(session=session),case['execution'],'cwd',{})
    assert snapshot['history'][-1]['arguments']==raw
