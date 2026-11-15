"""rc.3 durable system-prompt and runtime-context surface decisions."""
import re
from dsh.core.runtime_context import SOURCE, CLEARED, _UNSET, is_owned
from dsh.core.session.current import SURFACE_EVENT_TYPES
from dsh.llm.message import create_system_message, create_user_message


def text_of(message):
    content = message['content']
    if len(content) == 1 and isinstance(content[0], dict) and content[0].get('type') == 'text':
        return content[0].get('text')
    return None


class SystemPromptProjection:
    def __init__(self, session):
        self.session = session

    def _message(self, text):
        return create_system_message(text, SOURCE, format_version=getattr(self.session, 'format_version', 3))

    def project(self, rendered, input):
        nodes = []
        for seq in self.session.surface.nodes:
            event = self.session.eventAt(seq)
            if event is not None and event['type'] == 'system/message':
                message = event['data']['message']
                nodes.append(dict(seq=seq, text='' if not message['content'] else text_of(message)))
        if not nodes:
            return [dict(message=self._message(rendered), intent=dict(surfaceOp='append'))]
        head = nodes[0]
        latest = next((node for node in reversed(nodes) if node['text'] != ''), head)
        if (not input['inHistory'] or not rendered
                or input['startsSeries'] and (getattr(self.session, 'format_version', 3) != 4 or latest['text'] != rendered)):
            updates = [self._replace(node['seq'], '') for node in nodes[1:] if node['text'] != '']
            if head['text'] != rendered:
                updates.append(self._replace(head['seq'], rendered))
            return updates
        if latest['text'] == rendered:
            return []
        return [dict(message=self._message(rendered), intent=dict(surfaceOp='append'))]

    def _replace(self, seq, text):
        return dict(message=self._message(text), intent=dict(
            surfaceOp=dict(op='replace', startSeq=seq, endSeq=seq), sourceEventSeqs=[seq]))


class RuntimeContextProjection:
    def __init__(self, ctx, session):
        self.session, self._retained_state = session, _UNSET
        surface = set(session.surface.nodes)
        for event in reversed(session.snapshotEvents()):
            if event['type'] != 'user/message' or not self._is_owned(event['data']):
                continue
            if self._retained_state is _UNSET:
                self._retained_state = None
            if event['seq'] in surface:
                self._retained_state = self._state(event)
                break
        ctx.on('session/event', self._on_event)

    def _is_owned(self, message):
        if getattr(self.session, 'format_version', 3) == 4:
            return message['source']['kind'] == 'runtime-context'
        return is_owned(message)

    def _state(self, event):
        message = event['data']
        if getattr(self.session, 'format_version', 3) == 4:
            return dict(seq=event['seq'], sections=message['source'].get('sections', _UNSET)
                        if message['source'].get('form') == 'snapshot' else _UNSET)
        return dict(seq=event['seq'], text=text_of(message))

    def _on_event(self, subject, event):
        if subject is not self.session:
            return
        if event['type'] == 'user/message' and self._is_owned(event['data']):
            self._retained_state = self._state(event)
        elif (isinstance(self._retained_state, dict) and event['type'] in SURFACE_EVENT_TYPES
              and isinstance(event.get('surfaceOp'), dict)
              and self._retained_state['seq'] in event.get('sourceEventSeqs', [])):
            self._retained_state = None

    def project(self, current, sections):
        if getattr(self.session, 'format_version', 3) == 4:
            previous = self._retained_state.get('sections', _UNSET) if isinstance(self._retained_state, dict) else _UNSET
            if self._retained_state is _UNSET and not sections:
                return None
            if previous is not _UNSET and previous == sections:
                return None
            intro = ('The following information describes your current session:' if self._retained_state is _UNSET else
                     'The following information describes your current session. It replaces earlier versions of this context, including any retained in conversation summaries.')
            body = re.sub(r'</system-reminder\s*>', lambda match: '<\\' + match.group()[1:],
                          '\n\n'.join(section['text'] for section in sections), flags=re.IGNORECASE)
            snapshot = ('<system-reminder>\n' + intro + '\n\n' + body + '\n</system-reminder>' if sections else
                        '<system-reminder>\nCurrent runtime context: none. Earlier runtime-context snapshots no longer apply.\n</system-reminder>')
            return create_user_message(dict(content=[dict(type='text', text=snapshot)],
                                            source=dict(kind='runtime-context', form='snapshot', sections=sections)))
        if self._retained_state is _UNSET and not current:
            return None
        snapshot = current if current else CLEARED
        if isinstance(self._retained_state, dict) and self._retained_state['text'] == snapshot:
            return None
        source = dict(kind='plugin', plugin=SOURCE)
        if sections:
            source.update(form='snapshot', sections=sections)
        return create_user_message(dict(content=[dict(type='text', text=snapshot)], source=source))
