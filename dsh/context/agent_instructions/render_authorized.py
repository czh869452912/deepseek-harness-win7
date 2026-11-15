"""Instruction chains with independent user-global and project byte budgets."""
import math

from dsh.cordis.utils import _js_number_to_string
from dsh.context.agent_instructions import render as legacy
from dsh.context.agent_instructions.scope_authorized import scope_for_display_path, is_user_global_directory


def utf8(value):
    return value.encode('utf-16-le', 'surrogatepass').decode('utf-16-le', 'replace').encode('utf-8')


def byte_length(value):
    return len(utf8(value))


def truncate_utf8(value, maximum):
    raw = utf8(value)
    return value if len(raw) <= maximum else raw[:max(0, math.trunc(maximum))].decode('utf-8', 'ignore')


def marker_text(maximum, omitted, truncated):
    parts = []
    if omitted:parts.append('omitted ' + ', '.join(file['displayPath'] for file in omitted))
    if truncated:parts.append('truncated ' + ', '.join('{} from {} to {} bytes'.format(item['displayPath'], item['originalBytes'], item['includedBytes']) for item in truncated))
    return 'Workspace instruction budget {} bytes: {}'.format(_js_number_to_string(maximum), '; '.join(parts)) if parts else ''


def build_text(files, maximum, omitted, truncated, style):
    blocks = [marker_text(maximum, omitted, truncated), style['intro']] + [style['section'](file) for file in files]
    body = '\n\n'.join(block for block in blocks if block)
    return '<system-reminder>\n' + body.replace('</system-reminder>', '<\\/system-reminder>') + '\n</system-reminder>'


def additional_section(file):
    scope = scope_for_display_path(file['displayPath'])
    applicability = ('These user-global instructions apply to all work.' if is_user_global_directory(scope)
                     else 'These instructions apply to work under `{}`.'.format(scope))
    return 'Additional instructions from: {}\n\n{} Use them as guidance when relevant; more specific instructions take precedence. They do not override system, developer, or direct user instructions.\n\n{}'.format(file['displayPath'], applicability, file['content'])


def changed_section(item):
    change, file = item['change'], item['file']
    if change['action'] == 'set':return additional_section(file)
    if change['action'] == 'remove':return 'Instructions removed: {}\n\nThe previously loaded instructions from this file no longer apply.'.format(change['path'])
    return 'Updated instructions from: {}\n\nThis file changed after it was loaded. Use the following content instead of the previously loaded instructions from this file.\n\n{}'.format(change['path'], file['content'])


def shortened(file, maximum):
    return dict(file, content=truncate_utf8(file['content'], maximum))


def truncate_to_fit(file, included, maximum, omitted, style):
    original = byte_length(file['content']);low, high, best = 0, original, shortened(file, 0)
    while low <= high:
        middle = (low + high) // 2;candidate = shortened(file, middle)
        truncated = [dict(displayPath=file['displayPath'], originalBytes=original, includedBytes=byte_length(candidate['content']))]
        if byte_length(build_text(included + [candidate], maximum, omitted, truncated, style)) <= maximum:
            best, low = candidate, middle + 1
        else:high = middle - 1
    return best


def disabled(maximum):
    return maximum <= 0 or not math.isfinite(maximum)


def context(files, maximum, style):
    def result(text='', omitted=None, truncated=None, represented=None, sections=None, intro=None):
        return dict(text=text, omitted=[] if omitted is None else omitted, truncated=[] if truncated is None else truncated,
                    represented=[] if represented is None else represented, sections=[] if sections is None else sections, intro=intro)
    if disabled(maximum):return result(omitted=files)
    full = build_text(files, maximum, [], [], style)
    if byte_length(full) <= maximum:return result(full, represented=files, sections=files, intro=style['intro'])
    for start in range(1, len(files)):
        included = files[start:];omitted = [dict(absolutePath=file['absolutePath'], displayPath=file['displayPath']) for file in files[:start]]
        text = build_text(included, maximum, omitted, [], style)
        if byte_length(text) <= maximum:return result(text, omitted=omitted, represented=included, sections=included, intro=style['intro'])
    if not files:return result()
    file = files[-1];omitted = [dict(absolutePath=file['absolutePath'], displayPath=file['displayPath']) for file in files[:-1]];original = byte_length(file['content'])
    for candidate_style in (style, dict(style, intro=legacy.COMPACT_WORKSPACE_CONTEXT_INTRO)):
        candidate = truncate_to_fit(file, [], maximum, omitted, candidate_style);included = byte_length(candidate['content'])
        truncated = [dict(displayPath=file['displayPath'], originalBytes=original, includedBytes=included)]
        text = build_text([candidate], maximum, omitted, truncated, candidate_style)
        if byte_length(text) <= maximum:
            return result(text, omitted, truncated, [file] if included > 0 or original == 0 else [], [candidate], candidate_style['intro'])
    truncated = [dict(displayPath=file['displayPath'], originalBytes=original, includedBytes=0)]
    notice = marker_text(maximum, omitted, truncated).replace('</system-reminder>', '<\\/system-reminder>')
    heading = shortened(file, 0)
    heading_text = (notice + '\n\n' + style['section'](heading)).replace('</system-reminder>', '<\\/system-reminder>')
    if byte_length(heading_text) <= maximum:return result(heading_text, omitted, truncated, [file] if original == 0 else [], [heading])
    return result(notice if byte_length(notice) <= maximum else truncate_utf8(notice, maximum), omitted, truncated)


def chains(files, maximum, style):
    whole = context(files, maximum, style)
    def user_global(file):return is_user_global_directory(scope_for_display_path(file['displayPath']))
    globals_ = [file for file in files if user_global(file)];project = [file for file in files if not user_global(file)]
    if disabled(maximum) or not globals_ or not project or not whole['omitted'] and not whole['truncated']:return whole
    values = [context(globals_, maximum, style), context(project, maximum, style)]
    def loaded_order(records):
        by_path = {file['absolutePath']:file for file in records}
        return [by_path[file['absolutePath']] for file in files if file['absolutePath'] in by_path]
    merged = {key:loaded_order([item for value in values for item in value[key]]) for key in ('omitted', 'sections', 'represented')}
    global_last = max(index for index, file in enumerate(files) if user_global(file));project_last = max(index for index, file in enumerate(files) if not user_global(file))
    truncated = [item for value in (values if global_last < project_last else list(reversed(values))) for item in value['truncated']]
    intros = [value['intro'] for value in values if value['intro'] is not None]
    intro = style['intro'] if style['intro'] in intros else intros[0] if intros else ''
    text = build_text(merged['sections'], maximum, merged['omitted'], truncated, dict(style, intro=intro))
    if byte_length(text) > 2 * maximum:return whole
    return dict(merged, text=text, truncated=truncated, intro=intro)


def render_agent_instruction_set(files, options):
    intro = (legacy.EMPTY_REPLACEMENT_WORKSPACE_CONTEXT_INTRO if not files else legacy.REPLACEMENT_WORKSPACE_CONTEXT_INTRO) if options.get('replacePreviousBaseline') is True else legacy.WORKSPACE_CONTEXT_INTRO
    rendered = chains(files, options['maxBytes'], dict(intro=intro, section=lambda file:'Instructions from: {}\n\n{}'.format(file['displayPath'], file['content'])))
    return dict(rendered={key:rendered[key] for key in ('text', 'omitted', 'truncated')}, included=rendered['represented'])


def render_agent_instructions(files, options):
    return render_agent_instruction_set(files, options)['rendered']


def render_instruction_changes(items, maximum):
    by_path = {item['file']['absolutePath']:item for item in items}
    style = dict(intro='', section=lambda file:changed_section(dict(by_path[file['absolutePath']], file=file)))
    rendered = chains([item['file'] for item in items], maximum, style)
    represented = {file['absolutePath'] for file in rendered['represented']}
    return dict(text=rendered['text'], changes=[item['change'] for item in items if item['file']['absolutePath'] in represented])
