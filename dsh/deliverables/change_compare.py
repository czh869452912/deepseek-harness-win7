"""Line edit paths and three-line unified hunks matching the pinned diff API."""
# Adapted from jsdiff 9.0.0 Diff/structuredPatch (Kevin Decker and contributors).
# Copyright and redistribution terms are retained in JSDIFF-LICENSE.txt.
import math
import time


def _terminated(text):
    text = text or ''
    return text if text == '' or text.endswith('\n') else text+'\n'


def _tokens(text):
    return [] if text == '' else [line+'\n' for line in text[:-1].split('\n')]


def _components(old, new, timeout):
    deadline = math.floor(time.monotonic()*1000)+timeout
    best = {0: (-1, None)}

    def common(path, diagonal):
        old_pos, component = path
        new_pos, count = old_pos-diagonal, 0
        while new_pos+1 < len(new) and old_pos+1 < len(old) and old[old_pos+1] == new[new_pos+1]:
            old_pos, new_pos, count = old_pos+1, new_pos+1, count+1
        if count:
            component = (count, False, False, component)
        return (old_pos, component), new_pos

    def values(last):
        result = []
        while last is not None:
            result.append(last)
            last = last[3]
        old_pos, new_pos, groups = 0, 0, []
        for count, added, removed, _ in reversed(result):
            lines = old[old_pos:old_pos+count] if removed else new[new_pos:new_pos+count]
            if not removed:
                new_pos += count
            if not added:
                old_pos += count
            groups.append(dict(added=added, removed=removed, lines=lines))
        return groups

    def extend(path, added, removed, increment):
        old_pos, last = path
        if last is not None and last[1] == added and last[2] == removed:
            last = (last[0]+1, added, removed, last[3])
        else:
            last = (1, added, removed, last)
        return old_pos+increment, last

    best[0], new_pos = common(best[0], 0)
    if best[0][0]+1 >= len(old) and new_pos+1 >= len(new):
        return values(best[0][1])
    minimum, maximum = -math.inf, math.inf
    edit_length = 1
    while edit_length <= len(new)+len(old) and math.floor(time.monotonic()*1000) <= deadline:
        diagonal = int(max(minimum, -edit_length))
        end = min(maximum, edit_length)
        while diagonal <= end:
            remove_path, add_path = best.get(diagonal-1), best.get(diagonal+1)
            if remove_path is not None:
                best.pop(diagonal-1, None)
            can_add = add_path is not None and 0 <= add_path[0]-diagonal < len(new)
            can_remove = remove_path is not None and remove_path[0]+1 < len(old)
            if not can_add and not can_remove:
                best.pop(diagonal, None)
                diagonal += 2
                continue
            path = (extend(add_path, True, False, 0) if not can_remove or can_add and remove_path[0] < add_path[0]
                    else extend(remove_path, False, True, 1))
            path, new_pos = common(path, diagonal)
            if path[0]+1 >= len(old) and new_pos+1 >= len(new):
                return values(path[1])
            best[diagonal] = path
            if path[0]+1 >= len(old):
                maximum = min(maximum, diagonal-1)
            if new_pos+1 >= len(new):
                minimum = max(minimum, diagonal+1)
            diagonal += 2
        edit_length += 1
    return None


def compareText(before, after, timeoutMs):
    old_text, new_text = _terminated(before), _terminated(after)
    old, new = _tokens(old_text), _tokens(new_text)
    groups = _components(old, new, timeoutMs)
    coarse = groups is None
    if coarse:
        hunks = [dict(oldStart=1, oldLines=len(old), newStart=1, newLines=len(new),
            lines=['-'+line[:-1] for line in old]+['+'+line[:-1] for line in new])]
    else:
        groups.append(dict(added=False, removed=False, lines=[]))
        hunks, body = [], []
        old_start = new_start = 0
        old_line = new_line = 1
        for index, group in enumerate(groups):
            lines = group['lines']
            if group['added'] or group['removed']:
                if old_start == 0:
                    old_start, new_start = old_line, new_line
                    body = [' '+line for line in groups[index-1]['lines'][-3:]] if index else []
                    old_start -= len(body)
                    new_start -= len(body)
                body.extend(('+' if group['added'] else '-')+line for line in lines)
                if group['added']:
                    new_line += len(lines)
                else:
                    old_line += len(lines)
            else:
                if old_start:
                    if len(lines) <= 6 and index < len(groups)-2:
                        body.extend(' '+line for line in lines)
                    else:
                        context = min(len(lines), 3)
                        body.extend(' '+line for line in lines[:context])
                        hunks.append(dict(oldStart=old_start, oldLines=old_line-old_start+context,
                            newStart=new_start, newLines=new_line-new_start+context, lines=[line[:-1] for line in body]))
                        old_start = new_start = 0
                        body = []
                old_line += len(lines)
                new_line += len(lines)
    added = sum(line.startswith('+') for hunk in hunks for line in hunk['lines'])
    deleted = sum(line.startswith('-') for hunk in hunks for line in hunk['lines'])
    return dict(hunks=hunks, coarse=coarse, added=added, deleted=deleted)
