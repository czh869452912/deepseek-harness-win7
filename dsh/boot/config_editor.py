"""Profile-owned raw Config edits serialized with Loader hot reload."""
import copy
import os
import yaml

from dsh.boot.profile import compose_entries, load_profile_directory
from dsh.boot.profile_context import read_profile_patches
from dsh.boot.recomposition import reconcile_profile_patches
from dsh.boot.runtime_resolution import _field
from dsh.cordis.file_lock import with_file_lock
from dsh.cordis.fiber import FiberState
from dsh.cordis.loader import js_constructor
from dsh.cordis.service import Service
from dsh.util.atomic_write import write_file_atomic


class PatchLoader(yaml.SafeLoader):
    pass
PatchLoader.add_constructor('tag:yaml.org,2002:js', js_constructor)


class PatchDumper(yaml.SafeDumper):
    pass


def represent_config(dumper, value):
    if len(value) == 1 and isinstance(value.get('__jsExpr'), str):
        return dumper.represent_scalar('tag:yaml.org,2002:js', value['__jsExpr'])
    return dumper.represent_dict(value)
PatchDumper.add_representer(dict, represent_config)


def flatten(rows):
    result = []
    for row in rows:
        result.append(row)
        if row.get('group') and isinstance(row.get('config'), list):
            result.extend(flatten(row['config']))
    return result


def edit_patch_document(before, identity, name, next_config, inherited):
    rows = yaml.load(before, Loader=PatchLoader)
    if not isinstance(rows, list):
        raise ValueError('Profile patch must be a YAML sequence')
    nodes = yaml.compose(before, Loader=PatchLoader)
    matching = [index for index, row in enumerate(rows) if isinstance(row, dict)
        and row.get('id') == identity and 'insert' not in row
        and ('name' not in row or row['name'] == name)]
    changed = {}
    if next_config == inherited:
        for index, row in enumerate(rows):
            if not isinstance(row, dict) or row.get('id') != identity or 'insert' in row:
                continue
            replacement = dict(row)
            replacement.pop('config', None)
            changed[index] = None if set(replacement).issubset({'id', 'name'}) else replacement
    elif matching:
        index = matching[-1]
        changed[index] = dict(rows[index], config=next_config)
    else:
        rows.append(dict(id=identity, name=name, config=next_config))
    def dump(value):
        return yaml.dump(value, Dumper=PatchDumper, sort_keys=False, allow_unicode=True)
    # Preserve untouched block rows byte-for-byte, including their comments and tags.
    # Changed row values are emitted as YAML, with expression nodes restored as !!js.
    if nodes.flow_style or not nodes.value:
        output = [changed.get(index, row) for index, row in enumerate(rows)]
        return before[:nodes.start_mark.index] + dump([row for row in output if row is not None])
    edits = []
    def last_value_end(node):
        if isinstance(node, yaml.MappingNode) and not node.flow_style and node.value:
            return last_value_end(node.value[-1][1])
        if isinstance(node, yaml.SequenceNode) and not node.flow_style and node.value:
            return last_value_end(node.value[-1])
        return node.end_mark.index
    for index, replacement in changed.items():
        node = nodes.value[index]
        if replacement is not None and not node.flow_style and next_config != inherited:
            value_node = next((value for key, value in node.value if key.value == 'config'), None)
            # Replace only the Config value; surrounding row comments, name and
            # other metadata still belong to the user's document.
            value = yaml.dump(next_config, Dumper=PatchDumper, sort_keys=False,
                allow_unicode=True, default_flow_style=True, width=1000000).rstrip()
            if value_node is not None:
                edits.append((value_node.start_mark.index, last_value_end(value_node), value))
            else:
                end = last_value_end(node)
                line_end = before.find('\n', end)
                line_end = len(before) if line_end < 0 else line_end
                edits.append((line_end, line_end, '\n  config: ' + value))
            continue
        start = before.rfind('\n', 0, node.start_mark.index) + 1
        end = node.end_mark.index
        # End marks can include the next row's indentation; retain that prefix.
        line_start = before.rfind('\n', 0, end) + 1
        if before[line_start:end].strip() == '':
            end = line_start
        edits.append((start, end, '' if replacement is None else dump([replacement])))
    result = before
    for start, end, value in reversed(edits):
        result = result[:start] + value + result[end:]
    if len(rows) > len(nodes.value):
        result = result.rstrip() + '\n' + dump(rows[len(nodes.value):])
    return result


class ConfigEditor(Service):
    inject = ['loader', 'profileContext']

    def __init__(self, ctx, config=None):
        super().__init__(ctx, 'configEditor')
        self.owner_context = ctx

    @property
    def documentPath(self):
        return _field(self.owner_context.get('profileContext'), 'patchPath')

    def entries(self):
        candidates = [entry for entry in self.owner_context.loader.entries()
            if getattr(getattr(entry.parent.tree.ctx.fiber, 'entry', None), 'id', None) == 'include']
        counts = {}
        for entry in candidates:
            identity = entry.options['id']
            counts[identity] = counts.get(identity, 0) + 1
        return [entry for entry in candidates if counts[entry.options['id']] == 1]

    def inherited(self, entry, loaded):
        patches = []
        for patch in loaded.patches:
            patch = copy.deepcopy(patch)
            if patch.get('id') == entry.options['id'] and 'insert' not in patch:
                patch.pop('config', None)
            patches.append(patch)
        rows = flatten(compose_entries([*[layer.patches for layer in loaded.layers], patches]))
        row = next((row for row in rows if row.get('id') == entry.options['id']), {})
        return copy.deepcopy(row.get('config') or {})

    def configuration(self):
        profile = self.owner_context.get('profileContext')
        loaded = load_profile_directory('dsh', _field(profile, 'dir'), _field(profile, 'installAnchor'))
        entries = self.entries()
        overridden = {patch.get('id') for patch in loaded.patches if 'insert' not in patch and 'config' in patch}
        composed = {}
        if any(entry.options['id'] not in overridden for entry in entries):
            for row in flatten(compose_entries([*[layer.patches for layer in loaded.layers], loaded.patches])):
                composed.setdefault(row['id'], row)
        return [dict(entry=entry, inherited=self.inherited(entry, loaded) if entry.options['id'] in overridden else
            copy.deepcopy(composed.get(entry.options['id'], {}).get('config') or {}), override=copy.deepcopy(next((
                patch['config'] for patch in reversed(loaded.patches) if patch.get('id') == entry.options['id']
                and patch.get('config') is not None), {}))) for entry in entries]

    async def edit(self, entry, change):
        async def locked():
            profile = self.owner_context.get('profileContext')
            if entry not in self.entries() or entry.fiber is None:
                raise RuntimeError('Configuration entry is no longer available')
            before_patches = read_profile_patches('dsh', profile)
            await reconcile_profile_patches(self.owner_context.root, before_patches, 'dsh')
            if entry not in self.entries():
                raise RuntimeError('Configuration entry changed during reload')
            current = copy.deepcopy(entry.options.get('config') or {})
            loaded = load_profile_directory('dsh', _field(profile, 'dir'), _field(profile, 'installAnchor'))
            inherited = self.inherited(entry, loaded)
            next_config = change(current, inherited)
            fiber = entry.fiber
            if fiber.state != FiberState.ACTIVE:
                raise RuntimeError('Configuration plugin is no longer active')
            fiber.resolveConfig(next_config)
            try:
                with open(self.documentPath, encoding='utf-8', newline='') as stream:
                    before = stream.read()
            except FileNotFoundError:
                before = '[]\n'
            document = edit_patch_document(before, entry.options['id'], entry.options['name'], next_config, inherited)
            loaded.patches = yaml.load(document, Loader=PatchLoader)
            patches = read_profile_patches('dsh', profile, loaded)
            effective = next((row for row in flatten(compose_entries([patches])) if row['id'] == entry.options['id']), {})
            if (effective.get('config') or {}) != next_config:
                raise RuntimeError('Configuration for "{}" is overridden by a home patch or command-line overlay'.format(entry.options['id']))
            await write_file_atomic(self.documentPath, document, mode=0o600)
            try:
                await reconcile_profile_patches(self.owner_context.root, patches, 'dsh', [entry.options['id']])
            except Exception:
                await write_file_atomic(self.documentPath, before, mode=0o600)
                await reconcile_profile_patches(self.owner_context.root, before_patches, 'dsh')
                raise
        async def run():
            profile = self.owner_context.get('profileContext')
            return await with_file_lock(os.path.join(_field(profile, 'dir'), 'package.json'), locked)
        hmr = self.owner_context.get('hmr')
        return await run() if hmr is None else await hmr.runExclusive(run)
