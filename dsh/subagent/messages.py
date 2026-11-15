"""Named model relays and runtime-owned settlement notices."""
from dsh.cordis.json_text import stringify_json
from dsh.cordis.utils import js_to_string
from dsh.llm.message import create_user_message


def create_agent_message(sender, sender_name, content):
    return create_user_message(dict(content=[dict(type='text',text='Agent %s sent a message: ' % sender_name)]+list(content),
        source=dict(kind='agent-message',form='relay',senderSessionId=sender.id)))


def with_result_delivery_guidance(prompt):
    return list(prompt)+[dict(type='text',text='Your final answer is delivered automatically if your '
        'parent is still online. Include the result and relevant evidence in that answer; the parent does not '
        'receive your full transcript, tool output, or reasoning. If your last action is a message to your '
        'parent, the completion notice omits your final answer; include the result and relevant evidence in that message.')]


def settlement_summary(child_name, reason, continuable):
    completed = ('finished and will do no further work unless you send it more.' if continuable else
                 'finished. It cannot receive follow-up messages.')
    ending = dict(completed=completed,aborted='was stopped before it finished.',
                  refusal='declined the task.',error='failed before it finished.').get(reason)
    if reason == 'max-tokens':
        ending = 'ran out of room before it finished.'
    if ending is None:
        ending = 'ended abnormally (%s) before it finished.' % js_to_string(reason)
    return 'Background subagent %s %s' % (child_name,ending)


def create_settlement_message(child_id, child_name, terminal, continuable=True, omit_closing_text=False):
    summary = settlement_summary(child_name,terminal['stopReason'],continuable)
    closing = [block for block in terminal['output'] if block.get('type') == 'text' and len(block['text']) > 0]
    content = [dict(type='text',text=summary)]
    if omit_closing_text:
        content.append(dict(type='text',text='It sent you a message just before finishing, so its closing message is omitted.'))
    elif closing:
        content.extend([dict(type='text',text='Its closing message:')]+closing)
    else:
        content.append(dict(type='text',text='It left no closing message.'))
    if 'structured' in terminal:
        content.append(dict(type='text',text='Structured result: '+stringify_json(terminal['structured'])))
    if 'diagnostic' in terminal:
        content.append(dict(type='text',text=terminal['diagnostic']))
    encoded = summary.encode('utf-16-le',errors='surrogatepass')
    bounded = summary if len(encoded) <= 240 else encoded[:238].decode('utf-16-le',errors='surrogatepass')+'\u2026'
    return create_user_message(dict(content=content,source=dict(kind='subagent-settled',form='notice',summary=bounded,
        stopReason=terminal['stopReason'],senderSessionId=child_id)))


createAgentMessage = create_agent_message
createSettlementMessage = create_settlement_message
withResultDeliveryGuidance = with_result_delivery_guidance
