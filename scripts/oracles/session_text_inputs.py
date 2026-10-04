import argparse
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
parser = argparse.ArgumentParser()
parser.add_argument('--output', type=Path, required=True)
output = parser.parse_args().output.resolve()
source = ROOT / 'dsh/session/bin/unicode/CaseFolding.txt'
classes = {}
for line in source.read_text(encoding='utf-8').splitlines():
    parts = line.split('#')[0].strip().split(';')
    if len(parts) < 3 or parts[1].strip() not in ('C', 'S'):
        continue
    original = int(parts[0], 16)
    mapped = int(parts[2].strip(), 16)
    classes.setdefault(mapped, set()).update([original, mapped])
cases = []
for members in classes.values():
    for left in sorted(members):
        for right in sorted(members):
            cases.append(dict(name='fold-' + hex(left) + '-' + hex(right), text=chr(left), document=chr(right)))
ordered = sorted(classes)
for index, mapped in enumerate(ordered):
    other = ordered[(index + 1) % len(ordered)]
    cases.append(dict(name='distinct-' + hex(mapped) + '-' + hex(other), text=chr(mapped), document=chr(other)))
for left, right in [('ß', 'ss'), ('İ', 'i'), ('ı', 'I'), ('ẞ', 'ß'), ('s', 'ſ'), ('k', 'K'), ('é', 'e\u0301'),
                    ('a\u0315\u0300', 'à\u0315'), ('[.*+?^${}()|\\]', '[.*+?^${}()|\\]'), ('a\0b', 'A\0B'),
                    ('😀', '\ud83d\ude00'), ('\ud800', '\ud800'), ('\udc00', '\udc00')]:
    cases.append(dict(name='special-' + str(len(cases)), text=left, document=right))
spaces = list(range(9, 14)) + [32, 160, 0x1680] + list(range(0x2000, 0x200b)) + [0x2028, 0x2029, 0x202f, 0x205f, 0x3000, 0xfeff]
for codepoint in spaces + [0x1c, 0x1d, 0x1e, 0x1f, 0x85, 0x180e, 0x200b, 0x2060]:
    value = chr(codepoint)
    cases.extend([dict(name='trim-' + hex(codepoint), text=value + ' x ' + value, document='x'),
                  dict(name='separator-' + hex(codepoint), text='a b', document='A' + value + 'B'),
                  dict(name='empty-' + hex(codepoint), text=value, document='')])
events = []
for codepoint in spaces + [0x1c, 0x85, 0x180e, 0x200b]:
    value = chr(codepoint)
    content = [{'type': 'text', 'text': value + ' a ' + value}, {'type': 'reasoning', 'text': 'private'},
               {'type': 'tool-call', 'id': 'call', 'name': value + ' tool ' + value, 'arguments': value + '{}' + value},
               {'type': 'tool-result', 'toolCallId': 'call', 'content': [{'type': 'text', 'text': value + ' result ' + value}]},
               {'type': 'unknown', 'text': 'private'}]
    events.append(dict(type='user/message', data=dict(content=content)))
    events.append(dict(type='assistant/message', data=dict(message=dict(content=content))))
    events.append(dict(type='tool/call', data=dict(name=value + ' tool ' + value, arguments=value + '{}' + value)))
    events.append(dict(type='tool/result', data=dict(message=dict(content=content), error=dict(name=value+' error '+value, code=value+' code '+value))))
    events.append(dict(type='todo/write', data=dict(todos=[dict(status=value+' pending '+value, content=value+' task '+value)])))
    events.append(dict(type='turn/end', data=dict(reason=dict(kind='error', error=dict(message=value+' failed '+value)))))
events.extend(dict(type='turn/end', data=dict(reason=dict(kind=kind))) for kind in ('aborted', 'max-tokens', 'interrupted', 'completed', 'unknown'))
events.extend(dict(type=kind, data=dict(text='private')) for kind in ('turn/start', 'step/start', 'step/end', 'assistant/chunk', 'request/header', 'unknown'))
events.append(dict(type='user/message', data=dict(content=[dict(type='tool-result', toolCallId='nested', content=[dict(type='tool-result', toolCallId='inner', content=[dict(type='text', text='\ufeff deep \ufeff')]), dict(type='reasoning', text='private'), dict(type='image', url='private')])])))
events.append(dict(type='todo/write', data=dict(todos=[])))
report = dict(caseFoldingSha256=hashlib.sha256(source.read_bytes()).hexdigest(), cases=cases, events=events)
identities = ['a', 'A', 'á', 'a\u0301', 'ä', 'z', '中', '文', '阿', '😀', '🐍', 'ab', 'a\u200bb',
              'a\u00adb', '10', '2', '-', '_', 'é', 'e\u0301', 'Å', 'å', 'Ａ', 'ａ', 'ß', 'ss', 'İ', 'i', 'ı']
orders = []
for reverse in (False, True):
    values = list(reversed(identities)) if reverse else list(identities)
    for times in ('same', 'mixed', 'separate'):
        for provider in ('live', 'persisted', 'mixed'):
            headers = [dict(version=0, id='root', createdAt=0)]
            headers.extend(dict(version=0, id=identity, createdAt=1 if times == 'same' else index % 3 + 1 if times == 'mixed' else index + 1,
                                parentSession='root') for index, identity in enumerate(values))
            orders.append(dict(name=str(reverse)+'-'+times+'-'+provider, provider=provider, headers=headers))
report['orders'] = orders
output.parent.mkdir(parents=True, exist_ok=True)
output.write_text(json.dumps(report, ensure_ascii=True, indent=2)+'\n', encoding='utf-8')
print(json.dumps(dict(cases=len(cases), events=len(events), caseFoldingSha256=report['caseFoldingSha256'])))
