"""Compare Logger severities, exporter ownership and record isolation."""
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe


async def native():
    from dsh.cordis import Context
    from dsh.cordis.logger import Exporter,Logger
    from dsh.cordis.errors import AggregateError
    ctx=Context();result={}
    rows=[];disposers=[]
    for threshold in (None,0,1,2,3):
        received=[];rows.append(received)
        levels={} if threshold is None else {'default':threshold,'named':None}
        disposers.append(ctx.logger.exporter(Exporter(export_fn=lambda msg,out=received:out.append([msg.type,msg.level,msg.sn]),levels=levels)))
    log=ctx.logger('named')
    for name in ('error','warn','info','debug'):getattr(log,name)('hello')
    result['levels']=[[row[:] for row in received] for received in rows]
    disposers[0]();result['disposer']=[2 in ctx.logger.exporters,6 in ctx.logger.exporters]
    # Exporters see independent message objects; args deliberately stay shared.
    before=[];after=[]
    def mutate(msg):
        before.append(msg);msg.name='changed';msg.args.append('shared')
    ctx.logger.exporter(Exporter(export_fn=mutate))
    ctx.logger.exporter(Exporter(export_fn=lambda msg:after.append(msg)))
    log.info(None)
    result['records']=[before[-1] is not after[-1],after[-1].name,after[-1].args,ctx.logger.buffer[-1].name]
    log.info(AggregateError([]));result['empty_aggregate']=len(after)
    Logger('meta',ctx.logger,meta=dict(name='override',level=9,sn=123,args=['ignored'])).info('actual')
    result['meta']=[after[-1].name,after[-1].level,after[-1].sn,after[-1].args]
    ctx.logger.buffer_size=2;reference=ctx.logger.buffer
    child=ctx.extend()
    for value in range(4):child.logger('ring').info(value)
    result['buffer']=[reference is ctx.logger.buffer,len(reference),[msg.args[0] for msg in reference]]
    result['empty_name']=ctx.intercept('logger',{'name':'inherited'}).logger('').name
    await ctx.fiber.dispose()
    result['disposed']=len(ctx.logger.exporters)
    return result


if __name__=='__main__':
    probe.native=native
    probe.main(observer='rc022_logger.mts',scope='Logger severity/nullish thresholds, per-registration disposal, exporter record isolation, metadata precedence, empty aggregates and shared bounded buffer.',
        extra_inputs=[Path(__file__).resolve(),ROOT/'dsh/cordis/logger.py',ROOT/'.goose/out/rc022-prep-20261114-01/source/vendor/cordis/src/logger.ts'])
