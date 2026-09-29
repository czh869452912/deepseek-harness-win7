"""Host-wide replacement frames for Session queues, projections and jobs."""
import asyncio
import copy


def queue_items(agent, splice=None):
    result = []
    for target, source in [('next-turn', agent.inbox.next_turn), ('next-step', agent.inbox.next_step)]:
        messages = list(source)
        if splice is not None and splice['target'] == target:
            start = splice['start']
            messages[start:start + splice.get('removedCount', 0)] = splice['inserted']
        for message in messages:
            item = dict(id=message['id'], placement='queued' if target == 'next-turn' else 'steering' if message['source']['kind'] == 'user' else 'context',
                        message=dict(id=message['id'], content=message['content']))
            if message['source']['kind'] == 'user' and 'rpcId' in message['source']:
                item['rpcId'] = message['source']['rpcId']
            result.append(item)
    return result


class SessionControl:
    def __init__(self, ctx):
        self.ctx, self.followers = ctx, set()
        ctx.on('session/event', self.event)
        ctx.get('sessionProjections').onChanged(lambda session, key, value, seq: self.publish(dict(type='projection', sessionId=session.id, key=key, value=value, seq=seq)))
        ctx.inject(['jobs'], lambda child: child.get('jobs').onJobsChanged(self.jobs_changed))
        ctx.on('session/created', self.created)
        ctx.effect(lambda: self.close)

    def close(self):
        for queue in self.followers:
            queue.put_nowait(None)
        self.followers.clear()

    def jobs(self, agent):
        service = self.ctx.get('jobs')
        return [{key: row[key] for key in ('id', 'kind', 'label', 'status', 'detail', 'startedAt', 'finishedAt') if key in row}
                for row in service.list(agent)] if service is not None else []

    def publish(self, frame):
        for queue in self.followers:
            queue.put_nowait(copy.deepcopy(frame))

    def event(self, session, event):
        if event['type'] != 'agent/inbox/spliced':
            return
        agent = self.ctx.get('agents').get(session.id)
        if agent is not None and agent.session is session:
            self.publish(dict(type='queue', sessionId=session.id, items=queue_items(agent, event['data'])))

    def created(self, session):
        jobs = self.jobs(self.ctx.get('agents').get(session.id))
        if jobs:
            self.publish(dict(type='jobs', sessionId=session.id, jobs=jobs))

    def jobs_changed(self, owner):
        if owner is not None:
            self.publish(dict(type='jobs', sessionId=owner.id, jobs=self.jobs(owner)))
        else:
            for session in self.ctx.get('sessions').list():
                self.publish(dict(type='jobs', sessionId=session.id, jobs=self.jobs(self.ctx.get('agents').get(session.id))))

    def baseline(self):
        queues, jobs, projections = {}, {}, {}
        for session in self.ctx.get('sessions').list():
            agent = self.ctx.get('agents').get(session.id)
            queues[session.id] = queue_items(agent) if agent is not None and agent.session is session else []
            jobs[session.id] = self.jobs(agent)
            projections[session.id] = self.ctx.get('sessionProjections').snapshot(session)
        return dict(queues=queues, jobs=jobs, projections=projections)

    async def control(self, signal):
        signal.throw_if_aborted()
        queue = asyncio.Queue()
        self.followers.add(queue)
        release = signal.add_listener('abort', lambda *_: queue.put_nowait(None))
        try:
            yield dict(type='baseline', value=self.baseline())
            while not signal.aborted:
                frame = await queue.get()
                if frame is None:
                    return
                yield frame
        finally:
            release()
            self.followers.discard(queue)
