"""Candidate Team task board owned by the exact live subagent tree Lead."""
from dsh.cordis.plugin import Plugin
from dsh.cordis.schema import Schema
from dsh.typert.remote import TypertRemoteService,Remote
from dsh.team.errors import TeamError
from dsh.team.projection import TEAM,safe_integer
from dsh.team.journal import TeamJournal
from dsh.team.task_board import TeamTaskBoard


class TeamService(TypertRemoteService):
    def __init__(self,ctx,config,projection):
        super().__init__(ctx,'agentTeams')
        self.projection=projection
        self.journal=TeamJournal(self.ctx,projection)
        self.tasks=TeamTaskBoard(self.ctx,self.journal,config['maxTasks'])
        if config['defaultEnabled']:
            async def created(payload):
                agent=payload['agent']
                if payload['source']!='startup' or agent.session.header.get('origin')=='subagent':return
                if 'enabled' in projection.stateOf(agent.session):return
                await self.setEnabled(agent,True,payload['signal'])
            self.ctx.on('agent/created',created)

    def isEnabled(self,caller):
        root=self.ctx.get('subagents').rootOf(caller)
        return self.projection.stateOf(root.session).get('enabled') is True

    @Remote
    async def setEnabled(self,agent,enabled,signal=None):
        root=self.ctx.get('subagents').rootOf(agent)
        if root is not agent:raise TeamError('change Team mode from the root Session','TEAM_LEAD_REQUIRED')
        if signal is not None:signal.throwIfAborted()
        if self.isEnabled(root)!=enabled:root.session.append('team/mode',dict(enabled=enabled))
        await self.ctx.get('sessions').flush(root.session)

    async def createTask(self,caller,request,signal=None):
        return await self.tasks.create(caller,self.ctx.get('subagents').rootOf(caller),request,signal)

    def getTask(self,caller,identity):
        return self.tasks.get(self.ctx.get('subagents').rootOf(caller),identity)

    def listTasks(self,caller):
        return self.tasks.list(self.ctx.get('subagents').rootOf(caller))

    async def updateTask(self,caller,request,signal=None):
        return await self.tasks.update(caller,self.ctx.get('subagents').rootOf(caller),request,signal)


class TeamPlugin(Plugin):
    id='agent-team'
    inject=['agents','sessions','sessionPersistence','sessionProjections','subagents']
    Config=Schema.object(dict(maxTasks=Schema.number().step(1).min(1).default(256),defaultEnabled=Schema.boolean().default(False)))

    async def apply(self,ctx):
        for key in ('maxMembers','maxMessageBytes','disposalTimeoutMs'):
            if key in self.config:
                raise TeamError('agent-team: %s is no longer supported; teammates are subagents, so subagent limits and inbox delivery apply' % key,'TEAM_INVALID_CONFIG')
        if not safe_integer(self.config['maxTasks'],1):
            raise TeamError('maxTasks must be a positive safe integer','TEAM_INVALID_CONFIG')
        projection=await ctx.get('sessionProjections').register(TEAM)
        if ctx.fiber.uid is not None:TeamService(ctx,self.config,projection)
