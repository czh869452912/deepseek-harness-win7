import copy
import random


def chunk(sequence, kind='text-delta', payload='piece', **extra):
    body = dict(type=kind, index=0, **extra)
    if kind == 'tool-call-delta':
        body.update(id='call', argumentsDelta=payload)
    else:
        body['text'] = payload
    return dict(type='assistant/chunk', seq=sequence, time=sequence * 2 - 10, data=dict(turn=1.25, step=2.5, chunk=body))



def build_inputs(inventory_only=False):
    # Inventory checks need labels, not newly allocated observed payloads.
    # All real Source/native observers retain the complete default inputs.
    def events(factory):
        return [] if inventory_only else factory()

    packs = []
    for kind in ['text-delta', 'reasoning-delta', 'tool-call-delta']:
        for count in [0, 1, 2, 3, 4, 1024, 1025, 1026, 2051]:
            packs.append(dict(name=kind + '-' + str(count), events=events(lambda: [chunk(index, kind) for index in range(count)])))
    packs.extend([dict(name='utf8-bounded', events=events(lambda: [chunk(index, payload='界' * 120000) for index in range(5)])),
                  dict(name='individual-oversize', events=events(lambda: [chunk(index, payload='x' * 1048576) for index in range(3)])),
                  dict(name='presence-boundary', events=events(lambda: [chunk(index, 'tool-call-delta', name='tool') if index < 3 else chunk(index, 'tool-call-delta') for index in range(6)])),
                  dict(name='reversed-time', events=events(lambda: [dict(chunk(index), time=-index * 5) for index in range(5)]))])
    base = dict(type='text-chunks', seq0=0, time0=1, data=dict(turn=1.25, step=2.5, index=0.5, dt=[-2, 3], texts=['a', 'b', 'c']))
    decodes = [dict(name='valid', value=base), dict(name='scalar', value='scalar'), dict(name='null', value=None)]
    for name, mutation in [('extra-envelope', lambda value: value.update(extra=True)),
        ('negative-sequence', lambda value: value.update(seq0=-1)), ('time-fraction', lambda value: value.update(time0=1.5)),
        ('null-data', lambda value: value.update(data=None)), ('array-data', lambda value: value.update(data=[])),
        ('extra-data', lambda value: value['data'].update(extra=1)), ('boolean-turn', lambda value: value['data'].update(turn=True)),
        ('short-members', lambda value: value['data'].update(texts=['a', 'b'], dt=[1])),
        ('long-members', lambda value: value['data'].update(texts=['x'] * 1025, dt=[1] * 1024)),
        ('gap-shape', lambda value: value['data'].update(dt='bad')), ('gap-length', lambda value: value['data'].update(dt=[1])),
        ('gap-fraction', lambda value: value['data'].update(dt=[1.5, 2])),
        ('sequence-overflow', lambda value: value.update(seq0=9007199254740990)),
        ('time-overflow', lambda value: value.update(time0=9007199254740991)),
        ('oversize', lambda value: value['data'].update(texts=['x' * 1048576, 'b', 'c']))]:
        value = copy.deepcopy(base)
        mutation(value)
        decodes.append(dict(name=name, value=value))
    generator = random.Random(190057)
    values = [[], [0], [1], [127], [128], [16383], [16384], [9007199254740991],
              [0, 0], [1, 0], [9007199254740991, 0, 9007199254740991], list(range(100)),
              list(range(128, 300)), [0, 2, 4, 6], [-1], [1.5], [True], [9007199254740992]]
    for index in range(160):
        values.append([generator.randrange(0, 100000) for member in range(generator.randrange(0, 25))])
        start = generator.randrange(0, 100000)
        values.append(list(range(start, start + generator.randrange(1, 50))))
    payloads = ['', '00', '01', '0200', '0000', '008000', '0080', '00ffffffffffffffff7f',
                '000001', '010000', '010002', '0100010001', '0100010101', '010a14',
                '01feffffffffffff0f03', '01ffffffffffffff0f01']
    for index in range(120):
        payloads.append(bytes(generator.randrange(256) for member in range(generator.randrange(0, 18))).hex())
    varints = dict(encode=[dict(name='encode-%d' % index, values=value) for index, value in enumerate(values)],
                  decode=[dict(name='decode-%d-%d' % (index, bound), hex=value, seq=bound)
                          for index, value in enumerate(payloads) for bound in (0, 5, 100)])

    compression = [None, {}, {'text': 'x'}, {'text': 'x' * 10000}, {'content': [{'type': 'text', 'text': '界' * 1000}]},
                   ['x' * 10000], {'text': '𐀀' * 1000}, {'text': '\ud800' * 1000}, {'type': 'tool-call', 'arguments': 'large ' * 10000}]
    return dict(packs=packs, decodes=decodes, varints=varints, compression=compression)
