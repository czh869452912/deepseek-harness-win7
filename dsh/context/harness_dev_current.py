"""Stable dev prompt text and live location context, preserving admitted history."""
import json
import os
from pathlib import Path

from dsh.cordis.json_text import stringify_json
from dsh.cordis.plugin import Plugin
from dsh.typert.stores import field

CONSTANTS = json.loads(Path(__file__).with_name('harness_dev_text_current.json').read_text(encoding='utf-8'))['constants']
SOURCE_ROOT = os.path.join(str(Path(__file__).resolve().parents[2]), '')


def legacy_paragraph(prompt, markers):
    start = prompt.find(markers['prefix'])
    if start < 0: return None
    end = prompt.find(markers['suffix'], start+len(markers['prefix']))
    if end < 0: return None
    paragraph = prompt[start:end+len(markers['suffix'])]
    return None if '\n' in paragraph else paragraph


def fold_legacy_prompt(state, event):
    if event['type'] != 'system/message': return state
    content = event['data']['message']['content']
    if len(content) != 1 or content[0].get('type') != 'text' or content[0]['text'] == '': return state
    prompt = content[0]['text']
    updated = dict(source=legacy_paragraph(prompt, CONSTANTS['LEGACY_SOURCE']), web=legacy_paragraph(prompt, CONSTANTS['LEGACY_WEB_SURFACE']))
    return state if updated == state else updated


def legacy_state(value):
    if not isinstance(value, dict) or any(key not in value or value[key] is not None and not isinstance(value[key], str) for key in ('source', 'web')):
        raise ValueError('invalid admitted harness dev prompt')
    return dict(source=value['source'], web=value['web'])


class CurrentHarnessDevContext(Plugin):
    inject = ['systemPrompt', 'sessionProjections', 'webApp']

    async def apply(self, ctx):
        projection = await ctx.sessionProjections.register(dict(key='harnessDevLegacyPrompt', stateVersion=1,
            stateSchema=legacy_state, init=lambda *_:dict(source=None, web=None), apply=fold_legacy_prompt))
        def admitted(context):
            session = field(field(context, 'agent'), 'session')
            return dict(source=None, web=None) if session is None else projection.stateOf(session)
        prompt = ctx.systemPrompt
        prompt.section(dict(name='harness:source', order=prompt.getSectionOrder('HARNESS_SOURCE'), interpolate=False,
            text=lambda context:admitted(context)['source'] or CONSTANTS['HARNESS_SOURCE_PROMPT']))
        prompt.context(dict(name='harness:source', order=prompt.getContextOrder('HARNESS_SOURCE'), interpolate=False,
            text='Current DeepSeek Harness implementation checkout: '+stringify_json(SOURCE_ROOT)+'.'))
        prompt.section(dict(name='app:web-surface', order=prompt.getSectionOrder('WEB_SURFACE'), interpolate=False,
            text=lambda context:admitted(context)['web'] or CONSTANTS['WEB_SURFACE_PROMPT']))
        prompt.context(dict(name='app:web-surface', order=prompt.getContextOrder('WEB_SURFACE'), interpolate=False,
            text=lambda *_:'Current DeepSeek Harness Web GUI URL: '+stringify_json(ctx.webApp.getAdvertisedUrl())+'.'))
