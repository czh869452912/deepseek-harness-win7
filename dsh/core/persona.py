"""Scoped persona contribution to the canonical prompt registry."""
from dsh.cordis.plugin import Plugin
from dsh.core.system_prompt import PERSONA_ORDER, PERSONA_SECTION


class PersonaPlugin(Plugin):
    id = 'persona'
    name = '@deepseek-ai/dsh-persona'
    inject = ['systemPrompt']

    def apply(self, ctx):
        text = self.config.get('text')
        if not isinstance(text, str):
            raise ValueError('persona text is required')
        section = dict(name=PERSONA_SECTION, order=PERSONA_ORDER, text=text)
        if self.config.get('complete', False):
            section['complete'] = True
        ctx.effect(lambda: ctx.get('systemPrompt').section(section), 'persona.section()')
        if not self.config.get('includeRuntimeContext', True):
            ctx.get('systemPrompt').suppressRuntimeContext()
