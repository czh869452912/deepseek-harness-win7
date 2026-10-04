import copy


def build_inputs():
    
    metadata = dict(id='session', version=0, created_at=1234, cwd='C:\\workspace', parent_session=None,
                    seed_length=None, origin=None, delegation_depth=None, agent_preset=None,
                    incarnation='11111111-1111-4111-8111-111111111111', revision=0)
    event = dict(seq=0, type='turn/start', time=0, data='null', source_event_seqs=None, surface_op=None, is_packed=0)
    identities = dict(store_id='11111111-1111-4111-8111-111111111111')
    cases = []
    for category, base in [('metadata', metadata), ('event', event), ('identity', identities)]:
        cases.append(dict(name=category + '-valid', category=category, value=base))
        cases.extend(dict(name=category + '-root-' + str(index), category=category, value=value)
                     for index, value in enumerate([None, 'value', [], 1, False]))
        for key in base:
            value = copy.deepcopy(base)
            value.pop(key)
            cases.append(dict(name=category + '-' + key + '-missing', category=category, value=value))
            for index, replacement in enumerate([None, '', 'value', 0, -1, 1.5, True, [], {}, 9007199254740992]):
                value = copy.deepcopy(base)
                value[key] = replacement
                cases.append(dict(name=category + '-' + key + '-' + str(index), category=category, value=value))
    cases.extend([dict(name='identity-uppercase', category='identity', value=dict(store_id='ABCDABCD-ABCD-4ABC-8ABC-ABCDEFABCDEF')),
                  dict(name='metadata-valid-rooted-path', category='metadata', value=dict(metadata, cwd='\\workspace')),
                  dict(name='metadata-drive-relative-path', category='metadata', value=dict(metadata, cwd='C:workspace'))])
    return dict(cases=cases)
