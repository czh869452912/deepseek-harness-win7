"""Loader Config descriptors and live form edits through ConfigEditor."""
import asyncio
import os
import re
import yaml

from dsh.cordis.fiber import FiberState, resolve_config
from dsh.cordis.json_text import stringify_json
from dsh.cordis.loader import interpolate
from dsh.cordis.service import Service
from dsh.cordis.utils import _UNDEFINED
from dsh.settings.provider import SettingsConflictError, clone_json_shaped, merge_layers
from dsh.settings.redact import redact_secrets
from dsh.settings.schema_current import plain_config, project_form, volatile_form, is_volatile_path


def clone_config(value):
    if type(value) is not dict:
        raise TypeError('Config $ contains a non-plain root')
    return clone_json_shaped(value, lambda label, path: TypeError('Config {} contains {}'.format(path, label)))


def member(value, key):
    if type(value) is dict:
        return value.get(key, _UNDEFINED)
    if type(value) is list and re.fullmatch(r'0|[1-9][0-9]*', key):
        index = int(key)
        return value[index] if index < len(value) else _UNDEFINED
    return _UNDEFINED


def path_edit(section, operation, schema):
    def edit(value, path, node):
        if not path:
            return operation['value'] if operation['op'] == 'set' else _UNDEFINED
        head, rest = path[0], path[1:]
        if value is _UNDEFINED:
            value = node.meta.get('default', _UNDEFINED) if node is not None else _UNDEFINED
        if type(value) is list:
            if not re.fullmatch(r'0|[1-9][0-9]*', head) or int(head) > len(value) or (
                    int(head) == len(value) and (rest or operation['op'] == 'unset')):
                raise TypeError('Config array index "{}" is out of range'.format(head))
            result = list(value)
            index = int(head)
            if not rest and operation['op'] == 'unset':
                result.pop(index)
            else:
                child = edit(value[index] if index < len(value) else _UNDEFINED, rest, node.inner if node is not None else None)
                if index == len(result):
                    result.append(child)
                else:
                    result[index] = child
            return result
        result = dict(value) if type(value) is dict else {}
        child_node = ((node.dict or {}).get(head) or node.inner) if node is not None else None
        child = edit(result.get(head, _UNDEFINED), rest, child_node)
        if child is _UNDEFINED:
            result.pop(head, None)
        else:
            result[head] = child
        return result
    result = edit(section, operation['path'], schema)
    if type(result) is not dict:
        raise TypeError('Config root must be a plain object')
    return result


class SettingsForms(Service):
    inject = ['configEditor', 'profileContext']

    def __init__(self, ctx, config=None):
        super().__init__(ctx, 'settings')
        self.owner_context = ctx
        self.revisions = {}
        self.presentations = {}
        self.closed = False
        self.scheduled = False
        def close():
            self.closed = True
        ctx.effect(lambda: close)
        ctx.on('app-boot/config-reload', lambda *_: self.invalidate())

    async def init(self):
        # Import runs after the owning Loader has settled; it cannot block its own entry.
        async def import_after_settled():
            await self.owner_context.root.loader.await_()
            if not self.closed:
                await self.import_legacy_document()
        task = asyncio.create_task(import_after_settled())
        def observed(result):
            if not result.cancelled() and result.exception() is not None:
                self.owner_context.logger.error(result.exception())
        task.add_done_callback(observed)
        self.owner_context.effect(lambda: task.cancel)

    async def import_legacy_document(self):
        profile = self.owner_context.get('profileContext')
        home = profile['home'] if isinstance(profile, dict) else profile.home
        path = os.path.join(home, 'settings.yaml')
        if not os.path.exists(path):
            return
        imported = path + '.imported'
        os.replace(path, imported)
        with open(imported, encoding='utf-8') as stream:
            sections = yaml.safe_load(stream) or {}
        names = {'ui-developer-tools': 'ui-settings', 'ui-onboarding': 'ui-settings-general',
                 'shell': 'pwsh-sandbox' if os.name == 'nt' else 'bash-sandbox'}
        for section, values in sections.items():
            ns = names.get(section, section)
            try:
                await self.update(ns, values)
            except Exception as error:
                self.owner_context.logger.warn('settings: section %s of %s was not imported into entry %s', section, imported, ns)
                self.owner_context.logger.warn(error)

    def configure(self, presentation, owner=None):
        fiber = (owner.ctx if owner is not None else self.ctx).fiber
        if fiber in self.presentations:
            raise RuntimeError('Settings presentation is already configured for this plugin instance')
        policy = dict(presentation)
        self.presentations[fiber] = policy
        self.invalidate()
        def dispose():
            if self.presentations.get(fiber) is policy:
                del self.presentations[fiber]
                self.invalidate()
        return dispose

    def invalidate(self):
        if self.scheduled or self.closed:
            return
        self.scheduled = True
        def refresh():
            self.scheduled = False
            if self.closed or self.owner_context.fiber.state != FiberState.ACTIVE:
                return
            try:
                self.describe()
            except Exception as error:
                self.owner_context.logger.error(error)
        asyncio.get_running_loop().call_soon(refresh)

    @property
    def writable(self):
        return True

    @property
    def documentPath(self):
        return self.owner_context.get('configEditor').documentPath

    async def prepareDocument(self):
        return self.documentPath

    @staticmethod
    def schema(entry):
        runtime = getattr(getattr(entry, 'fiber', None), 'runtime', None)
        schema = getattr(runtime, 'Config', None)
        return schema if callable(getattr(schema, 'toJSON', None)) else None

    def describe(self, options=None):
        active, descriptors = set(), []
        for row in self.owner_context.get('configEditor').configuration():
            entry, inherited, override = row['entry'], row['inherited'], row['override']
            schema = self.schema(entry)
            if schema is None or entry.fiber.state != FiberState.ACTIVE:
                continue
            form = volatile_form(schema)
            if form is None:
                continue
            active.add(entry.id)
            raw = stringify_json([entry.fiber.uid, schema.toJSON(), entry.options.get('config', {})])
            auto = self.presentations.get(entry.fiber.ctx.fiber, {}).get('auto', True)
            previous = self.revisions.get(entry.id)
            revision = 0 if previous is None else previous['revision'] + int(previous['raw'] != raw)
            self.revisions[entry.id] = dict(raw=raw, revision=revision, ns=entry.options['id'], autoGenerate=auto)
            if previous is None or previous['raw'] != raw or previous['autoGenerate'] != auto:
                self.owner_context.emit('settings/document-updated', entry.options['id'], revision)
            value = project_form(form, plain_config(entry.fiber.effectiveConfig))
            resolved = interpolate(entry.fiber.ctx, inherited)
            try:
                resolved = resolve_config(None, resolved, entry.fiber.runtime)
            except Exception:
                pass
            base = project_form(form, plain_config(resolved))
            user = project_form(form, override)
            descriptor = dict(autoGenerate=auto, ns=entry.options['id'], schema=form.toJSON(), revision=revision, applies='live', value=value, base=base, user=user)
            if (options or {}).get('redactSecrets'):
                redacted = redact_secrets(form, value)
                descriptor.update(value=redacted.value, base=redact_secrets(form, base).value,
                    user=redact_secrets(form, user).value, secrets=[secret.to_dict() for secret in redacted.secrets])
            descriptors.append(descriptor)
        for identity, previous in tuple(self.revisions.items()):
            if identity not in active and previous['raw'] is not None:
                previous.update(raw=None, revision=previous['revision'] + 1)
                self.owner_context.emit('settings/document-updated', previous['ns'], previous['revision'])
        return descriptors

    async def update(self, ns, patch, expectedRevision=None):
        value = clone_config(patch)
        await self.write(ns, lambda current, base, schema: merge_layers(current, value), expectedRevision)

    async def replace(self, ns, section, expectedRevision=None):
        value = clone_config(section)
        await self.write(ns, lambda current, base, schema: merge_layers(base, value), expectedRevision)

    async def mutate(self, ns, operations, expectedRevision=None):
        def change(current, base, schema):
            for operation in operations:
                if operation['op'] == 'unset':
                    parent = current
                    for key in operation['path'][:-1]:
                        parent = member(parent, key)
                    inherited = base
                    for key in operation['path']:
                        inherited = member(inherited, key)
                    if type(parent) is not list and inherited is not _UNDEFINED:
                        operation = dict(op='set', path=operation['path'], value=inherited)
                current = path_edit(current, operation, schema)
            return current
        await self.write(ns, change, expectedRevision, [operation['path'] for operation in operations])

    async def write(self, ns, change, expected=None, paths=()):
        editor = self.owner_context.get('configEditor')
        entry = next((row for row in editor.entries() if row.options['id'] == ns), None)
        schema = self.schema(entry)
        if entry is None or schema is None:
            raise RuntimeError('No configurable plugin entry "{}"'.format(ns))
        form = volatile_form(schema)
        if form is None:
            raise RuntimeError('Plugin entry "{}" has no volatile fields'.format(ns))
        for path in paths:
            if path and not is_volatile_path(schema, path):
                raise RuntimeError('Config field "{}" is not volatile'.format('.'.join(path)))
        def edit(raw, inherited):
            descriptor = next((row for row in self.describe() if row['ns'] == ns), None)
            if descriptor is None:
                raise RuntimeError('Plugin entry "{}" is no longer configurable'.format(ns))
            if expected is not None and descriptor['revision'] != expected:
                raise SettingsConflictError(ns, expected, descriptor['revision'])
            current, base = project_form(form, raw), project_form(form, inherited)
            value = clone_config(change(current, base, schema))
            def validate(value, node, path=()):
                for key, child in value.items():
                    target = [*path, key]
                    if is_volatile_path(schema, target):
                        continue
                    field = (node.dict or {}).get(key)
                    if type(child) is dict and field is not None:
                        validate(child, field, target)
                    else:
                        raise RuntimeError('Config field "{}" is not volatile'.format('.'.join(target)))
            validate(value, form)
            def strip(value, node, path=()):
                if is_volatile_path(schema, path):
                    return {}
                result = dict(value)
                for key, field in (node.dict or {}).items():
                    target = [*path, key]
                    if is_volatile_path(schema, target):
                        result.pop(key, None)
                    elif type(result.get(key)) is dict:
                        result[key] = strip(result[key], field, target)
                return result
            return merge_layers(strip(raw, form), value)
        await editor.edit(entry, edit)
        self.describe()
