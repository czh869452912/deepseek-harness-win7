"""Serialized per-Lead transactions over authoritative Session events."""
import asyncio
from dsh.cordis.awaiting import start_coroutine
from dsh.team.errors import TeamError


class TeamJournal:
    def __init__(self,ctx,projection):
        self.ctx,self.projection,self.tails=ctx,projection,{}

    def state(self,root):
        state=self.projection.stateOf(root.session)
        if 'failure' in state:raise RuntimeError(state['failure'])
        return state

    def transact(self,root_id,operation):
        prior=self.tails.get(root_id)
        tail=asyncio.get_running_loop().create_future()
        self.tails[root_id]=tail
        async def perform():
            try:
                if prior is None:await asyncio.sleep(0)
                else:await asyncio.shield(prior)
                return await operation()
            finally:
                tail.set_result(None)
                if self.tails.get(root_id) is tail:self.tails.pop(root_id)
        return start_coroutine(perform())

    async def append_and_flush(self,root,task):
        root.session.append('team/task',dict(version=2,teamId=root.id,task=task))
        try:
            if not await self.ctx.get('sessions').flush(root.session):
                raise RuntimeError('No session durability listener participated')
        except Exception as cause:
            raise TeamError('task "%s" revision %s is visible, but persistence was not confirmed; read the task before retrying' %
                            (task['id'],task['revision']),'TEAM_TASK_PERSISTENCE_UNCONFIRMED',cause=cause) from cause
