import re


DIFF_CONTEXT = 3


def _lines(value):
    return [part for part in re.findall(r'[^\n]*\n|[^\n]+$', value) if part]


def _step(path, added, removed, increment):
    previous = path['last']
    if previous is not None and previous[1:3] == (added, removed):
        component = (previous[0] + 1, added, removed, previous[3])
    else:
        component = (1, added, removed, previous)
    return dict(position=path['position'] + increment, last=component)


def _common(path, after, before, diagonal):
    old_position = path['position']
    new_position = old_position - diagonal
    count = 0
    while new_position + 1 < len(after) and old_position + 1 < len(before) and before[old_position + 1] == after[new_position + 1]:
        old_position += 1
        new_position += 1
        count += 1
    if count:
        path['last'] = (count, False, False, path['last'])
    path['position'] = old_position
    return new_position


def _components(last, after, before):
    reversed_components = []
    while last is not None:
        reversed_components.append(last[:3])
        last = last[3]
    old_position, new_position = 0, 0
    components = []
    for count, added, removed in reversed(reversed_components):
        if removed:
            selected = before[old_position:old_position + count]
            old_position += count
        else:
            selected = after[new_position:new_position + count]
            new_position += count
            if not added:
                old_position += count
        components.append(dict(added=added, removed=removed, lines=selected))
    return components


def _line_diff(before, after):
    before, after = _lines(before), _lines(after)
    initial = dict(position=-1, last=None)
    new_position = _common(initial, after, before, 0)
    if initial['position'] + 1 >= len(before) and new_position + 1 >= len(after):
        return _components(initial['last'], after, before)
    paths = {0: initial}
    maximum = len(before) + len(after)
    minimum_diagonal, maximum_diagonal = -maximum, maximum
    for distance in range(1, maximum + 1):
        for diagonal in range(max(minimum_diagonal, -distance), min(maximum_diagonal, distance) + 1, 2):
            remove_path, add_path = paths.get(diagonal - 1), paths.get(diagonal + 1)
            if remove_path is not None:
                paths.pop(diagonal - 1, None)
            can_add = add_path is not None and 0 <= add_path['position'] - diagonal < len(after)
            can_remove = remove_path is not None and remove_path['position'] + 1 < len(before)
            if not can_add and not can_remove:
                paths.pop(diagonal, None)
                continue
            path = _step(add_path, True, False, 0) if not can_remove or (can_add and remove_path['position'] < add_path['position']) else _step(remove_path, False, True, 1)
            new_position = _common(path, after, before, diagonal)
            if path['position'] + 1 >= len(before) and new_position + 1 >= len(after):
                return _components(path['last'], after, before)
            paths[diagonal] = path
            if path['position'] + 1 >= len(before):
                maximum_diagonal = min(maximum_diagonal, diagonal - 1)
            if new_position + 1 >= len(after):
                minimum_diagonal = max(minimum_diagonal, diagonal + 1)
    raise RuntimeError('Line difference did not reach both text ends')


def compute_hunk_diffs(path, before, after):
    components = _line_diff(before, after)
    components.append(dict(added=False, removed=False, lines=[]))
    pending = None
    hunks = []
    for index, component in enumerate(components):
        lines = component['lines']
        if component['added'] or component['removed']:
            if pending is None:
                previous = components[index - 1]['lines'][-DIFF_CONTEXT:] if index else []
                pending = [(' ', line) for line in previous]
            pending.extend(('+' if component['added'] else '-', line) for line in lines)
        elif pending is not None:
            if len(lines) <= DIFF_CONTEXT * 2 and index < len(components) - 2:
                pending.extend((' ', line) for line in lines)
            else:
                pending.extend((' ', line) for line in lines[:DIFF_CONTEXT])
                hunks.append(pending)
                pending = None
    result = []
    for hunk in hunks:
        old_lines, new_lines = [], []
        for kind, line in hunk:
            text = line[:-1] if line.endswith('\n') else line
            if kind != '+':
                old_lines.append(text)
            if kind != '-':
                new_lines.append(text)
        result.append(dict(path=path, oldText='\n'.join(old_lines) if old_lines else None, newText='\n'.join(new_lines)))
    return result


def diffs_from_meta(meta):
    if not isinstance(meta, dict) or not isinstance(meta.get('diffs'), list) or not meta['diffs']:
        return None
    for diff in meta['diffs']:
        if not isinstance(diff, dict) or not isinstance(diff.get('path'), str) or 'oldText' not in diff or not isinstance(diff.get('newText'), str):
            return None
        if diff['oldText'] is not None and not isinstance(diff['oldText'], str):
            return None
    return meta['diffs']
