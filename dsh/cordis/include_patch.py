"""Patch ownership and routing for Include's per-entry persistence journal."""
import secrets
from typing import Any, Callable, Dict, List, Optional

from dsh.cordis.include_journal import apply_changes, detach, flatten, place, _identity_index
from dsh.cordis.utils import _UNDEFINED


def ensure_ids(entries: List[Dict[str, Any]], used: Callable[[str], bool]) -> None:
    for entry in entries:
        if not entry.get('id'):
            while True:
                entry_id = secrets.token_hex(4)
                if not used(entry_id):
                    entry['id'] = entry_id
                    break
        if entry.get('group') and isinstance(entry.get('config'), list):
            ensure_ids(entry['config'], used)


def ensure_insert_ids(patches: Optional[List[Dict[str, Any]]], used: Callable[[str], bool]) -> None:
    for patch in patches or []:
        if isinstance(patch.get('insert'), list):
            ensure_ids(patch['insert'], used)


class PatchIndex:
    def __init__(self, patches: List[Dict[str, Any]]):
        self.patches = patches
        self.keys: Dict[str, Dict[str, int]] = {}
        self.inserts: Dict[str, Any] = {}
        for index, patch in enumerate(patches):
            entry_id = patch.get('id')
            if isinstance(patch.get('insert'), list):
                def walk(items: List[Dict[str, Any]], parent: Optional[str]) -> None:
                    for options in items:
                        self.inserts[options.get('id', _UNDEFINED)] = dict(
                            type='insert', index=index, list=items, options=options, parent=parent)
                        if options.get('group') and isinstance(options.get('config'), list):
                            walk(options['config'], options.get('id'))
                walk(patch['insert'], entry_id)
                continue
            if not entry_id:
                continue
            keys = self.keys.setdefault(entry_id, {})
            for key in patch:
                if key not in ('id', 'insert', 'name'):
                    keys[key] = index

    def entry(self, entry_id: Optional[str]) -> Dict[str, Any]:
        return self.inserts.get(entry_id, {'type': 'file'}) if entry_id is not None else {'type': 'file'}

    def key(self, entry_id: str, key: str) -> Dict[str, Any]:
        if entry_id in self.inserts:
            return self.inserts[entry_id]
        index = self.keys.get(entry_id, {}).get(key)
        return {'type': 'file'} if index is None else dict(type='patch', index=index)

    def file_owned(self, entry_id: str, key: Optional[str]) -> bool:
        return (self.entry(entry_id) if key is None else self.key(entry_id, key))['type'] == 'file'

    fileOwned = file_owned


def route_journal(journal: Dict[str, Any], data: List[Dict[str, Any]], patches: List[Dict[str, Any]],
                  warn: Optional[Callable[..., None]] = None) -> bool:
    index = PatchIndex(patches)
    patched = False
    warn = warn or (lambda *args: None)

    def place_at(options: Dict[str, Any], parent: Optional[str], position: Any) -> None:
        nonlocal patched
        owner = index.entry(parent)
        if owner['type'] == 'insert':
            if owner['options'].get('config') is None:
                owner['options']['config'] = []
            items = owner['options']['config']
            items.insert(int(min(position, len(items))), options)
            patched = True
        elif not place(data, options, parent, position):
            warn('cannot place entry %C: group %C not found', options['id'], parent)

    for entry_id, value in journal.items():
        owner = index.entry(entry_id)
        if value['kind'] == 'remove':
            if owner['type'] == 'insert':
                owner['list'].pop(_identity_index(owner['list'], owner['options']))
                patched = True
            else:
                detach(data, entry_id)
            continue
        current = owner if owner['type'] == 'insert' else flatten(data).get(entry_id)
        parent = value.get('parent', _UNDEFINED)
        if current is None:
            options = {'id': entry_id}
            apply_changes(options, value['changes'])
            place_at(options, None if parent is _UNDEFINED else parent, value['position'])
            continue
        if parent is not _UNDEFINED and current['parent'] != parent:
            if owner['type'] == 'insert':
                owner['list'].pop(_identity_index(owner['list'], owner['options']))
                patched = True
            else:
                detach(data, entry_id)
            apply_changes(current['options'], value['changes'])
            place_at(current['options'], parent, value['position'])
            continue
        if owner['type'] == 'insert':
            apply_changes(current['options'], value['changes'])
            patched = True
            continue
        patch_changes: Dict[int, Dict[str, Any]] = {}
        def file_key(key: str) -> bool:
            key_owner = index.key(entry_id, key)
            if key_owner['type'] != 'patch':
                return True
            patch_changes.setdefault(key_owner['index'], {})[key] = value['changes'][key]
            return False
        apply_changes(current['options'], value['changes'], file_key)
        for patch_index, changes in patch_changes.items():
            apply_changes(patches[patch_index], changes)
            patched = True
    return patched


ensureIds = ensure_ids
ensureInsertIds = ensure_insert_ids
routeJournal = route_journal
