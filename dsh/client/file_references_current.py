"""Current desktop-style file guidance shared by Web and SDK compositions."""
import json
from pathlib import Path

from dsh.cordis.plugin import Plugin

FILE_REFERENCE_SECTION = json.loads(Path(__file__).with_name('file_reference_prompt_current.json').read_text(encoding='utf-8'))


class CurrentDeliverableFileReferences(Plugin):
    inject = ['systemPrompt']

    def apply(self, ctx):
        section = dict(FILE_REFERENCE_SECTION)
        section['order'] = ctx.systemPrompt.getSectionOrder(section['order'])
        ctx.systemPrompt.section(section)
