"""Deterministic clock pairing for the actual SDK multi-round budget driver."""
import asyncio
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe


def cases():
    rows=[dict(name='budget-'+str(budget),budget=budget,firstMs=100,paceMs=250,legMs=30,rounds=1) for budget in (0,-1,100,300,350,351,500,1000)]
    rows.extend([dict(name='many-rounds',budget=900,firstMs=100,paceMs=250,legMs=30,rounds=3),
        dict(name='success-many',budget=1000,firstMs=100,paceMs=250,legMs=30,rounds=3),
        dict(name='round-cap-first',budget=600,firstMs=100,paceMs=250,legMs=30,rounds=3,maxRounds=1),
        dict(name='options-boundary',budget=900,firstMs=10,paceMs=250,legMs=20,rounds=2,options=dict(timeout=123,resetTimeoutOnProgress=True,headers={'x-probe':'owned'},relatedRequestId=42,resumptionToken='single-leg',allowInputRequired=False)),
        dict(name='no-total-budget',firstMs=100,paceMs=250,legMs=30,rounds=2)])
    return rows


async def observe():
    import dsh.mcp.negotiated_protocol_current as module
    output=[];previous_now,previous_pace=module.now_ms,module.pace_state_only
    try:
        for case in cases():
            clock=[0];retries=[];progress=[]
            module.now_ms=lambda:clock[0]
            async def pace(signal):clock[0]+=case['paceMs'];await asyncio.sleep(0)
            module.pace_state_only=pace
            class Transport(module.NegotiatedProtocol):
                negotiated=dict(era='modern');protocol_version='2026-07-28'
                input_required=dict(maxRounds=case.get('maxRounds',10))
                count=0
                async def _request_leg(self,packet,signal,timeout,options):
                    self.count+=1
                    if self.count==1:clock[0]+=case['firstMs']
                    else:
                        retries.append(dict(state=packet['params'].get('requestState'),options={k:v for k,v in options.items() if k!='onprogress'},keys=sorted(options)))
                        clock[0]+=case['legMs']
                    return (dict(resultType='input_required',requestState='state'+str(self.count)) if self.count<=case['rounds']
                        else dict(resultType='complete',tools=[],ttlMs=0,cacheScope='private'))
            options=dict(case.get('options',{}),onprogress=progress.append)
            if 'budget' in case:options['maxTotalTimeout']=case['budget']
            try:result=dict(value=await Transport().request(dict(method='tools/list'),request_options=options))
            except Exception as error:result=dict(error=dict(name=getattr(error,'name','Error'),message=str(error),code=error.code,data=error.data))
            output.append(dict(name=case['name'],result=result,retries=retries,progress=progress,elapsed=clock[0]))
    finally:module.now_ms,module.pace_state_only=previous_now,previous_pace
    return output


def prepare(output):
    path=output/'cases.json';path.write_text(json.dumps(cases()),encoding='utf-8');return [path]


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_mcp_flow_budget.mts','Actual SDK multi-round driver with deterministic Date.now and owned pacing-clock collaborator, compared to Native modern dispatch. First-leg accounting, exact exhaustion, shrinking retry budgets, original per-leg timeout and retry option ownership. Wire transport timers are a separate contract.',
        extra_inputs=[Path(__file__).resolve(),ROOT/'dsh/mcp/negotiated_protocol_current.py'],prepare=prepare)
