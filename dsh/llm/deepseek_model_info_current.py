"""Messages model capabilities and reasoning choices for one connection generation."""
import copy
from urllib.parse import urlsplit
import re

MESSAGES_FILES_BETA = 'files-api-2025-04-14'
MESSAGES_TOOL_CHANGES_BETA = 'mid-conversation-tool-changes-2026-07-01'
_EFFORTS = [dict(id=key,name=name,description=description) for key,name,description in [
    ('off','Off','Use for simple tasks that do not need reasoning.'),
    ('low','Low','Prefer for routine or latency-sensitive tasks.'),
    ('high','High','The default balance for most tasks.'),
    ('max','Max','Reserve for the hardest quality-first tasks.')]]


def messagesApiRoot(baseURL):
    base = baseURL.rstrip('/')
    normalized = re.sub(r'[\t\r\n]','',base).replace('\\','/')
    normalized = re.sub(r'^(https?):/*',r'\1://',normalized,flags=re.I)
    return base if urlsplit(normalized).path.endswith('/v1') else base+'/v1'


def catalogModelInfo(provider, model, badge=None):
    result = dict(provider=provider,id=model['id'],name=model.get('name') if model.get('name') is not None else model['id'],
                  inputModalities=copy.deepcopy(model.get('inputModalities') if model.get('inputModalities') is not None else ['text']))
    if 'description' in model: result['description'] = model['description']
    if badge is not None: result['badge'] = copy.deepcopy(badge)
    return result


def modelInfo(connection, provider, model):
    configured = next((entry for entry in connection['models'] if entry['id'] == model),dict(id=model))
    result = catalogModelInfo(provider,configured)
    result['context'] = dict(contextWindow=configured.get('contextWindow',connection['defaultContextWindow']))
    result['defaultMaxTokens'] = configured.get('maxTokens',connection['maxTokens'])
    for key in ('systemPromptUpdate','toolUpdate'):
        if key in configured: result[key] = configured[key]
    disabled = connection['defaults'].get('thinking') == 'disabled'
    effort = connection['defaults'].get('reasoningEffort')
    result['reasoning'] = dict(efforts=copy.deepcopy(_EFFORTS[:1] if disabled else _EFFORTS),
                               defaultEffort='off' if disabled else effort if effort in ('off','low','max') else 'high')
    return result
