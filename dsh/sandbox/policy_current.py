"""Current policy snapshots and exact-Session runtime directory grants."""
import os
from weakref import WeakKeyDictionary

from dsh.cordis.json_text import stringify_json
from dsh.cordis.schema import Schema
from dsh.cordis.service import Service
from dsh.cordis.utils import _UNDEFINED
from dsh.core.session.json import FrozenList
from dsh.jobs.pump import field
from dsh.llm.error import HarnessError
from .sandbox_policy import render_policy_context as previous_context,set_sandbox_mode
from .vocabulary import SANDBOX_MODES


class SandboxInvalidRootError(HarnessError):
    def __init__(self,path,detail,subject='additional writable directory'):
        super().__init__('Invalid '+subject+' '+stringify_json(path)+': '+detail,'SANDBOX_INVALID_ROOT')


def execution_world_path(path):return os.path.isabs(path) and '\0' not in path


def resolve_additional_roots(roots):
    if not roots:return None
    if any(not execution_world_path(root) for root in roots):raise ValueError('sandbox-policy: writable directories must be absolute execution-world paths without NUL bytes')
    return FrozenList(dict.fromkeys(roots))


def mode_schema(value):
    if value is not None and value not in SANDBOX_MODES:raise ValueError('invalid sandbox mode')
    return value


def render_policy_context(policy):
    if policy['mode']!='workspace-write':return previous_context(policy)
    additional=policy.get('additionalWritableRoots')
    extra='' if additional is None else ' Additional writable directories: '+stringify_json(additional)+'. On Windows, these additional grants apply to file tools only, not sandboxed processes.'
    return 'Current DSH file policy: workspace-write. Any available operation enforced by the DSH file sandbox may modify files under the session workspace: '+stringify_json(policy['workspaceRoot'])+'.'+extra+' Some platform temporary areas may also be writable.'


class CurrentSandboxPolicy(Service):
    inject=['sessionProjections']
    Config=Schema.object(dict(mode=Schema.union(*SANDBOX_MODES).default('read-only'),workspaceRoot=Schema.string(),additionalWritableRoots=Schema.array(Schema.string()).default([])))

    def __init__(self,ctx,config=None):
        super().__init__(ctx,'sandboxPolicy');config=config or {}
        self.defaultMode=config.get('mode','read-only');self.workspaceRoot=config.get('workspaceRoot',_UNDEFINED)
        if self.workspaceRoot is _UNDEFINED:self.workspaceRoot=os.getcwd()
        if not execution_world_path(self.workspaceRoot):raise ValueError('sandbox-policy: workspace root must be an absolute execution-world path without NUL bytes')
        self.additionalWritableRoots=resolve_additional_roots(config.get('additionalWritableRoots'));self.writable_roots=WeakKeyDictionary()

    async def init(self):
        ctx=self.ctx
        self.projection=await ctx.sessionProjections.register(dict(key='sandboxMode',stateVersion=1,stateSchema=mode_schema,init=lambda *_:None,apply=lambda state,event:event['data']['mode'] if event['type']=='sandbox/mode' else state))
        def contribute(scope):
            def text(context):
                agent=field(context,'agent');session=field(agent,'session')
                return '' if session is None else render_policy_context(self.resolve(dict(session=session)))
            scope.systemPrompt.context(dict(name='sandbox:policy',order=scope.systemPrompt.getContextOrder('SANDBOX_POLICY'),text=text))
        ctx.inject(['systemPrompt'],contribute)

    def resolve(self,request=None):
        request=request or {};session=request.get('session');registrations=None if session is None else self.writable_roots.get(session)
        additional=self.additionalWritableRoots if registrations is None else resolve_additional_roots(list(self.additionalWritableRoots or [])+list(registrations.values()))
        mode=request.get('mode')
        if mode is None and session is not None:mode=self.overrideOf(session)
        if mode is None:mode=self.defaultMode
        cwd=field(field(session,'header'),'cwd') if session is not None else None
        if cwd is not None and not execution_world_path(cwd):raise SandboxInvalidRootError(cwd,'the Session working directory must be an absolute execution-world path without NUL bytes','sandbox workspace root')
        result=dict(mode=mode,workspaceRoot=self.workspaceRoot if cwd is None else cwd)
        if additional is not None:result['additionalWritableRoots']=additional
        if session is not None:result['sessionId']=session.id
        return result

    def registerWritableRoot(self,session,directory):
        resolve_additional_roots([directory])
        def setup():
            registrations=self.writable_roots.get(session)
            if registrations is None:registrations={};self.writable_roots[session]=registrations
            key=object();registrations[key]=directory
            def cleanup():
                registrations.pop(key,None)
                if not registrations:self.writable_roots.pop(session,None)
            return cleanup
        return self.ctx.effect(setup,label='sandboxPolicy.registerWritableRoot()')

    def overrideOf(self,session):return self.projection.stateOf(session)
    override_of=overrideOf
    register_writable_root=registerWritableRoot
