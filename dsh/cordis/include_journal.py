"""Per-entry persistence deltas and file-wins reconciliation (rc022 Include)."""
from typing import Any, Callable, Dict, List, Optional

from dsh.cordis.utils import _UNDEFINED, deep_equal


def diff_options(legacy: Dict[str, Any], options: Dict[str, Any]) -> Dict[str, Any]:
    changes = {}
    for key in dict.fromkeys(list(legacy) + list(options)):
        if key != 'id' and not deep_equal(legacy.get(key, _UNDEFINED), options.get(key, _UNDEFINED)):
            changes[key] = options.get(key, _UNDEFINED)
    return changes


def merge_records(older: Optional[Dict[str, Any]], newer: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if older is None:
        return newer
    if newer['kind'] == 'remove':
        return None if older['kind'] == 'upsert' and older['created'] else newer
    if older['kind'] == 'remove':
        return dict(newer, created=False)
    relocated = newer.get('parent', _UNDEFINED) is not _UNDEFINED
    return dict(kind='upsert', created=older['created'],
                parent=newer.get('parent', _UNDEFINED) if relocated else older.get('parent', _UNDEFINED),
                position=newer['position'] if relocated else older['position'],
                changes=dict(older['changes'], **newer['changes']))


def merge(journal: Dict[str, Any], entry_id: str, value: Dict[str, Any]) -> None:
    merged = merge_records(journal.get(entry_id), value)
    if merged is None:
        journal.pop(entry_id, None)
    else:
        journal[entry_id] = merged


def _identity_index(items: List[Any], target: Any) -> int:
    return next((i for i, item in enumerate(items) if item is target), -1)


def record(journal: Dict[str, Any], change: Dict[str, Any], parent: Optional[str]) -> None:
    entry_id = change['id']; options = change.get('options'); legacy = change.get('legacy')
    if options is None:
        merge(journal, entry_id, {'kind': 'remove'})
        return
    position = _identity_index(change['group'].data, options)
    merge(journal, entry_id, dict(kind='upsert', created=legacy is None,
          parent=parent if legacy is None or change.get('from') is not None else _UNDEFINED,
          position=position, changes={key: value for key, value in options.items() if key != 'id'}
          if legacy is None else diff_options(legacy, options)))


def flatten(data: List[Dict[str, Any]], parent: Optional[str] = None,
            result: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if result is None:
        result = {}
    for position, options in enumerate(data):
        if options.get('id'):
            result[options['id']] = dict(parent=parent, position=position, options=options, list=data)
        if options.get('group') and isinstance(options.get('config'), list):
            flatten(options['config'], options.get('id'), result)
    return result


def apply_changes(options: Dict[str, Any], changes: Dict[str, Any],
                  predicate: Optional[Callable[[str], bool]] = None) -> None:
    for key, value in changes.items():
        if predicate is not None and not predicate(key):
            continue
        if value is _UNDEFINED:
            options.pop(key, None)
        else:
            options[key] = value


def detach(data: List[Dict[str, Any]], entry_id: str) -> Optional[Dict[str, Any]]:
    flat = flatten(data).get(entry_id)
    if flat is None:
        return None
    flat['list'].pop(_identity_index(flat['list'], flat['options']))
    return flat['options']


def place(data: List[Dict[str, Any]], options: Dict[str, Any], parent: Optional[str], position: Any) -> bool:
    target = data
    if parent is not None:
        group = flatten(data).get(parent)
        if group is None or not group['options'].get('group'):
            return False
        if group['options'].get('config') is None:
            group['options']['config'] = []
        target = group['options']['config']
    index = min(position, len(target))
    target.insert(int(index), options)
    return True


def apply_journal(data: List[Dict[str, Any]], journal: Dict[str, Any],
                  predicate: Optional[Callable[[str, Optional[str]], bool]] = None,
                  warn: Optional[Callable[..., None]] = None) -> List[Dict[str, Any]]:
    predicate = predicate or (lambda entry_id, key: True)
    warn = warn or (lambda *args: None)
    for entry_id, value in journal.items():
        if not predicate(entry_id, None):
            continue
        if value['kind'] == 'remove':
            detach(data, entry_id)
            continue
        flat = flatten(data).get(entry_id)
        if flat is None:
            options = {'id': entry_id}
            apply_changes(options, value['changes'], lambda key: predicate(entry_id, key))
            parent = value.get('parent', _UNDEFINED)
            parent = None if parent is _UNDEFINED else parent
            if not place(data, options, parent, value['position']):
                warn('cannot place entry %C: group %C not found', entry_id, parent)
            continue
        apply_changes(flat['options'], value['changes'], lambda key: predicate(entry_id, key))
        parent = value.get('parent', _UNDEFINED)
        if parent is not _UNDEFINED and flat['parent'] != parent:
            detach(data, entry_id)
            if not place(data, flat['options'], parent, value['position']):
                warn('cannot move entry %C: group %C not found', entry_id, parent)
                place(data, flat['options'], flat['parent'], flat['position'])
    return data


def reconcile(journal: Dict[str, Any], base: Dict[str, Any], theirs: Dict[str, Any],
              file_owned: Callable[[str, Optional[str]], bool]) -> List[Dict[str, str]]:
    conflicts = []
    for entry_id, value in list(journal.items()):
        if not file_owned(entry_id, None):
            continue
        b = base.get(entry_id); t = theirs.get(entry_id)
        def conflict(reason: str) -> None:
            conflicts.append(dict(id=entry_id, reason=reason))
        if value['kind'] == 'remove':
            if t is None:
                journal.pop(entry_id)
            elif b is None or not deep_equal(t['options'], b['options']):
                conflict('modified in file, removed at runtime' if b else 'added in file, removed at runtime')
                journal.pop(entry_id)
            continue
        if t is None:
            if b is not None:
                conflict('removed in file, modified at runtime')
                journal.pop(entry_id)
            continue
        if value['created']:
            value['created'] = False
        for key in list(value['changes']):
            if not file_owned(entry_id, key):
                continue
            bv = b['options'].get(key, _UNDEFINED) if b is not None else _UNDEFINED
            tv = t['options'].get(key, _UNDEFINED)
            if deep_equal(bv, tv) or deep_equal(tv, value['changes'][key]):
                continue
            conflict('key "%s" modified both in file and at runtime' % key)
            del value['changes'][key]
        parent = value.get('parent', _UNDEFINED)
        if parent is not _UNDEFINED and b is not None and t['parent'] != b['parent'] and t['parent'] != parent:
            conflict('moved both in file and at runtime')
            value['parent'] = _UNDEFINED
        parent = value.get('parent', _UNDEFINED)
        moved = parent is not _UNDEFINED and parent != t['parent']
        if not value['changes'] and not moved:
            journal.pop(entry_id)
    return conflicts


diffOptions = diff_options
mergeRecords = merge_records
applyChanges = apply_changes
applyJournal = apply_journal
