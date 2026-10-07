from dsh.fs.fs_local import FsError
from dsh.fs.tool_diff import compute_hunk_diffs, diffs_from_meta


def remediate_fs_error(error):
    remedies = dict(FS_STALE_VERSION='re-read the file, then retry', FS_NOT_OBSERVED='read the file, then retry')
    remedy = remedies.get(error.code) if isinstance(error, FsError) else None
    return FsError('%s — %s' % (error, remedy), error.code, error) if remedy else error


def apply_mutation_tool(ctx, sandbox, kind):
    editing = kind == 'edit'
    if editing:
        description = 'Edit an existing UTF-8 text file by replacing literal text.'
        guidance = 'Use the edit tool for targeted changes to existing UTF-8 text files. It replaces literal old_string with new_string; by default old_string must appear exactly once. If old_string appears multiple times, provide a more specific old_string or set replace_all to true. Read the file first (the default fs-observation-policy requires it), unless you just created or edited it in this session.'
        properties = dict(old_string=dict(type='string', description='Literal text to replace. Must match exactly.'),
            new_string=dict(type='string', description='Literal replacement text. Use an empty string to delete the match.'),
            replace_all=dict(type='boolean', description='Replace all matches. Defaults to false; when false, old_string must appear exactly once.'))
        required = ['file_path', 'old_string', 'new_string']
        output_properties = dict(path=dict(type='string'), before=dict(type='string'), after=dict(type='string'))
    else:
        description = 'Create or fully replace a UTF-8 text file.'
        guidance = 'Use the write tool to create files or completely replace file contents. Existing files are overwritten, so read an existing file first (the default fs-observation-policy requires it) and prefer edit for targeted changes.'
        properties = dict(content=dict(type='string', description='Full UTF-8 text content to write.'))
        required = ['file_path', 'content']
        output_properties = dict(path=dict(type='string'), operation=dict(type='string', enum=['create', 'update']),
            before=dict(oneOf=[dict(type='string'), dict(type='null')]), after=dict(type='string'))
    parameters = dict(file_path=dict(type='string', description='Path to %s, resolved by the filesystem backend.' % kind), **properties)
    if sandbox.escalation_modes:
        parameters.update(sandbox.schema_fields())
    ctx.get('systemPrompt').section(dict(name='tool:' + kind, order=1300 if editing else 1200, text=guidance))

    async def execute(arguments, execution):
        from dsh.fs.tool_fs import _fire_waterfall, _observation_target
        if not arguments['file_path'].strip():
            raise ValueError('file_path must be a non-empty string')
        if editing:
            if not arguments['old_string']:
                raise ValueError('old_string must be a non-empty string')
            if arguments['old_string'] == arguments['new_string']:
                raise ValueError('old_string and new_string must differ')
        policy = await sandbox.resolve_policy(kind, arguments, execution)
        filesystem = ctx.get('fs')
        target = await _observation_target(filesystem, arguments['file_path'], execution, policy)
        options = dict(sandbox_policy=policy) if policy is not None else {}
        if not editing:
            intent = await _fire_waterfall(ctx, 'fs/write-intent', target, execution)
        try:
            if editing:
                intent = await _fire_waterfall(ctx, 'fs/edit-intent', target, execution)
                outcome = await filesystem.editText(target, dict(oldString=arguments['old_string'], newString=arguments['new_string'],
                    replaceAll=arguments.get('replace_all') or False), intent, execution.signal, **options)
            else:
                outcome = await filesystem.writeText(target, arguments['content'], intent, execution.signal, **options)
        except Exception as error:
            raise remediate_fs_error(sandbox.map_error(error, policy))
        ctx.emit('fs/observed', target, dict(kind='present', version=outcome.version), execution)
        result = dict(path=target.displayPath, before=outcome.before, after=outcome.after)
        if not editing:
            result['operation'] = outcome.operation
        return result

    def render(arguments, value):
        from dsh.fs.tool_fs import format_edit_output, format_write_output
        text = format_edit_output(value['path'], arguments.get('replace_all') or False) if editing else format_write_output(value['path'], value['operation'])
        return [dict(type='text', text=text)]

    def metadata(arguments, value):
        return dict(diffs=[] if value['before'] is None else compute_hunk_diffs(arguments['file_path'], value['before'], value['after']))

    def fallback(arguments):
        return [dict(path=arguments['file_path'], oldText=arguments['old_string'] or None if editing else None,
            newText=arguments['new_string'] if editing else arguments['content'])]

    def present_call(arguments):
        return dict(card='diff', title=kind.capitalize() + ' ' + arguments['file_path'], diffs=fallback(arguments), locations=[dict(path=arguments['file_path'])])

    def present_result(arguments, result):
        if result.get('isError'):
            return None
        diffs = diffs_from_meta(result.get('meta'))
        if diffs is None:
            if editing:
                return None
            diffs = fallback(arguments)
        return dict(card='diff', title=kind.capitalize() + ' ' + arguments['file_path'], diffs=diffs)

    ctx.get('tools').register(dict(name=kind, description=description,
        parameters=dict(type='object', properties=parameters, required=required),
        output=dict(schema=dict(type='object', additionalProperties=False, properties=output_properties, required=list(output_properties)),
            render=render, presentationMeta=metadata), execute=execute, presentCall=present_call, presentResult=present_result))
