def build_cases():
    user = dict(type='user/message', seq=0, time=0, surfaceOp='append',
                data=dict(content=[dict(type='text', text='legacy')], source=dict(kind='user')))
    replacement = dict(type='tool/result', seq=1, time=1, surfaceOp=dict(op='replace', start=0, deleteCount=1),
                       sourceEventSeqs=[0], data=dict(callId='call', content=[], isError=False))
    definitions = [
        ('future', 1, []), ('old', -1, []),
        ('unknown', 0, [dict(type='future/custom', seq=0, time=0, data={})]),
        ('legacy-delta', 0, [dict(type='request/header-delta', seq=0, time=0, data={})]),
        ('legacy-mode', 0, [dict(type='mode/set', seq=0, time=0, data={})]),
        ('legacy-fallback', 0, [dict(type='request/header', seq=0, time=0, data=dict(reason='fallback'))]),
        ('legacy-user', 0, [user]), ('legacy-replacement', 0, [user, replacement]),
        ('legacy-assistant', 0, [dict(type='assistant/message', seq=0, time=0,
            data=dict(content=[dict(type='text', text='old response')], provenance=dict(provider='p', model='m')))]),
        ('legacy-steering', 0, [dict(type='steering/message', seq=0, time=0,
            data=dict(turn=1, content=[dict(type='text', text='steered')], source=dict(kind='user')))]),
        ('malformed-steering', 0, [dict(type='steering/message', seq=0, time=0, data=dict(turn=1))]),
        ('legacy-start', 0, [dict(type='turn/start', seq=0, time=0, data=dict(turn=1, trigger=dict(kind='request')))]),
        ('malformed-start', 0, [dict(type='turn/start', seq=0, time=0, data=dict(turn=0, trigger=dict(kind='request')))]),
        ('legacy-disposed', 0, [dict(type='turn/start', seq=0, time=0, data=dict(turn=1)),
            dict(type='turn/end', seq=1, time=1, data=dict(turn=1, reason=dict(kind='disposed')))]),
        ('legacy-aborted', 0, [dict(type='turn/start', seq=0, time=0, data=dict(turn=1)),
            dict(type='turn/end', seq=1, time=1, data=dict(turn=1, reason=dict(kind='aborted')))]),
        ('legacy-error', 0, [dict(type='turn/start', seq=0, time=0, data=dict(turn=1)),
            dict(type='turn/end', seq=1, time=1, data=dict(turn=1, reason=dict(kind='error', step=0, message='failure')))]),
        ('malformed-end', 0, [dict(type='turn/end', seq=0, time=0, data=dict(turn=1))]),
        ('malformed-user', 0, [dict(type='user/message', seq=0, time=0, data=dict(id='id', role='assistant', content=[]))]),
    ]
    cases = [dict(name=name, version=version, events=events, sequence=1 if name == 'legacy-replacement' else 0)
             for name, version, events in definitions]
    cases.extend(dict(name='invalid-seek-' + str(index), version=0, events=[], sequence=value)
                 for index, value in enumerate([-1, 0.5, True, None, '1', {}]))
    cases.append(dict(name='missing', missing=True, sequence=0))
    return cases
