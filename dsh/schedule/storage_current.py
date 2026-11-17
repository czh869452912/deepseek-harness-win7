"""Version-2 Host tasks; compatible v1 reads never write or activate Sessions."""
import hashlib
import json

from dsh.cordis.text import trim_js
from dsh.cordis.utils import deep_equal
from dsh.core.session.json import UNDEFINED
from dsh.storage.domain_spec import define_domain,domain_table,SchemaValidator
from dsh.schedule.domain_current import decode_schedule_record,ScheduleLogError
from dsh.util_time_instant import four_digit_year_epoch


class ScheduleSchemaError(ValueError):
    name='ZodError'
    def __init__(self,issues):
        self.issues=issues;super().__init__(json.dumps(issues,ensure_ascii=False,indent=2))


class _TaskParser:
    def __init__(self):self.issues=[]
    def issue(self,path,code='custom',message='Invalid input',**fields):
        self.issues.append(dict(fields,code=code,path=path,message=message))
    def invalid(self,path,expected,value):
        received=('undefined' if value is UNDEFINED else 'null' if value is None else 'boolean' if type(value) is bool else
            'number' if type(value) in (int,float) else 'string' if isinstance(value,str) else 'array' if isinstance(value,list) else 'object')
        self.issue(path,'invalid_type','Invalid input: expected %s, received %s' % (expected,received),expected=expected)
    def obj(self,value,path,allowed):
        if not isinstance(value,dict):self.invalid(path,'object',value);return None
        extra=[key for key in value if key not in allowed]
        if extra:self.issue(path,'unrecognized_keys','Unrecognized key'+('s' if len(extra)>1 else '')+': '+', '.join(json.dumps(key) for key in extra),keys=extra)
        return value
    def string(self,value,path,minimum=False,trimmed=False):
        if not isinstance(value,str):self.invalid(path,'string',value);return value
        if minimum and not value:self.issue(path,'too_small','Too small: expected string to have >=1 characters',origin='string',minimum=1,inclusive=True)
        if trimmed and trim_js(value)!=value:self.issue(path)
        return value
    def instant(self,value,path):
        if not isinstance(value,str):self.invalid(path,'string',value);return value
        # Zod admits year zero at the ISO-format check, then the domain's
        # additional four-digit-year refinement refuses it explicitly.
        parsed=four_digit_year_epoch('2000'+value[4:] if value.startswith('0000-') else value)
        if parsed['kind']=='rejected':self.issue(path,'invalid_format','Invalid ISO datetime',format='datetime')
        if value.startswith('0000-'):self.issue(path,message='Expected a canonical four-digit-year UTC calendar instant')
        return value
    def boolean(self,value,path):
        if type(value) is not bool:self.invalid(path,'boolean',value)
        return value
    def strings(self,value,path):
        if not isinstance(value,list):self.invalid(path,'array',value);return value
        return [self.string(item,path+[index],minimum=True) for index,item in enumerate(value)]
    def create(self,value,path):
        obj=self.obj(value,path,{'cwd','agentPreset'})
        if obj is None:return value
        return {key:self.string(item,path+[key],minimum=True) for key,item in obj.items() if key in ('cwd','agentPreset')}
    def target(self,value,path):
        if not isinstance(value,dict):self.invalid(path,'object',value);return value
        kind=value.get('kind')
        if kind not in ('session','new_once','new'):
            self.issue(path+['kind'],'invalid_union','Invalid input',errors=[],note='No matching discriminator',discriminator='kind');return value
        allowed={'kind','sessionId'} if kind=='session' else {'kind','sessionId','create'} if kind=='new_once' else {'kind','create'}
        self.obj(value,path,allowed);result=dict(kind=kind)
        if kind=='session' or 'sessionId' in value:result['sessionId']=self.string(value.get('sessionId',UNDEFINED),path+['sessionId'],minimum=True)
        if kind!='session':result['create']=self.create(value.get('create',{}),path+['create'])
        return result
    def receipt(self,value,path,prompt=False):
        allowed={'scheduledAt','deliveredAt','messageId','targetSessionId'}|({'prompt'} if prompt else set())
        obj=self.obj(value,path,allowed)
        if obj is None:return value
        result={key:self.instant(obj.get(key,UNDEFINED),path+[key]) for key in ('scheduledAt','deliveredAt')}
        result['messageId']=self.string(obj.get('messageId',UNDEFINED),path+['messageId'],minimum=True,trimmed=True)
        if 'targetSessionId' in obj:result['targetSessionId']=self.string(obj['targetSessionId'],path+['targetSessionId'],minimum=True)
        if prompt and 'prompt' in obj:result['prompt']=self.string(obj['prompt'],path+['prompt'])
        return result
    def history(self,value,path):
        obj=self.obj(value,path,{'records','earlierRecordsUnavailable','earlierRecordsPruned'})
        if obj is None:return value
        records=obj.get('records',UNDEFINED);result={}
        if not isinstance(records,list):self.invalid(path+['records'],'array',records)
        else:
            result['records']=[self.receipt(item,path+['records',index],True) for index,item in enumerate(records)]
            identities=[item.get('messageId') for item in records if isinstance(item,dict) and isinstance(item.get('messageId'),str)]
            if len(set(identities))!=len(identities):self.issue(path,message='Delivery history message identities must be unique within a task')
        result['earlierRecordsUnavailable']=self.boolean(obj.get('earlierRecordsUnavailable',UNDEFINED),path+['earlierRecordsUnavailable'])
        result['earlierRecordsPruned']=self.boolean(obj.get('earlierRecordsPruned',False),path+['earlierRecordsPruned'])
        return result


def default_session_id(id):
    # Node's UTF-8 encoder replaces lone UTF-16 surrogates with U+FFFD.
    text=id.encode('utf-16-le','surrogatepass').decode('utf-16-le','replace')
    return 'session-schedule-'+hashlib.sha256(text.encode('utf-8')).hexdigest()


def parse_schedule_task(value):
    parser=_TaskParser();allowed={'record','sessionId','target','involvedSessionIds','status','createdAt','updatedAt','lastDelivery','deliveryHistory','pendingDelivery'}
    obj=parser.obj(value,[],allowed)
    if obj is None:raise ScheduleSchemaError(parser.issues)
    task={}
    try:task['record']=decode_schedule_record(obj.get('record'))
    except ScheduleLogError as error:parser.issue(['record'],message=error.name+': '+str(error))
    if 'target' in obj:task['target']=parser.target(obj['target'],['target'])
    if 'involvedSessionIds' in obj:task['involvedSessionIds']=parser.strings(obj['involvedSessionIds'],['involvedSessionIds'])
    status=obj.get('status','active')
    if status not in ('active','paused','ended','inactive'):parser.issue(['status'],'invalid_value','Invalid option: expected one of "active"|"paused"|"ended"|"inactive"',values=['active','paused','ended','inactive'])
    task['status']=status
    for key in ('createdAt','updatedAt'):
        if key in obj:task[key]=parser.instant(obj[key],[key])
    if 'lastDelivery' in obj:task['lastDelivery']=parser.receipt(obj['lastDelivery'],['lastDelivery'])
    if 'deliveryHistory' in obj:task['deliveryHistory']=parser.history(obj['deliveryHistory'],['deliveryHistory'])
    if 'pendingDelivery' in obj:
        pending=parser.obj(obj['pendingDelivery'],['pendingDelivery'],{'targetSessionId'})
        if pending is not None:task['pendingDelivery']=dict(targetSessionId=parser.string(pending.get('targetSessionId',UNDEFINED),['pendingDelivery','targetSessionId'],minimum=True))
    if parser.issues:raise ScheduleSchemaError(parser.issues)
    saved_target=task.get('target');binding=None
    if saved_target is None and 'sessionId' in obj:
        binding=obj['sessionId']
        if not isinstance(binding,str) or not binding:
            parser.issue(['sessionId'],message='A missing target requires a valid stored Session binding');raise ScheduleSchemaError(parser.issues)
    if saved_target is None:
        target=dict(kind='session',sessionId=binding) if binding is not None else dict(kind='new_once',sessionId=default_session_id(task['record']['id']),create={})
    elif saved_target['kind']=='new_once':target=dict(saved_target,sessionId=saved_target.get('sessionId',default_session_id(task['record']['id'])))
    else:target=saved_target
    known_target=(binding is not None if saved_target is None else saved_target['kind']!='new' and 'sessionId' in saved_target)
    receipts=([task['lastDelivery']] if 'lastDelivery' in task else [])+task.get('deliveryHistory',{}).get('records',[])
    if not known_target and any('targetSessionId' not in receipt for receipt in receipts):
        parser.issue([],message='A saved delivery without an existing destination must name its target Session');raise ScheduleSchemaError(parser.issues)
    def receipt(value):return dict(value,targetSessionId=value.get('targetSessionId',target.get('sessionId')))
    last=receipt(task['lastDelivery']) if 'lastDelivery' in task else None
    history=task.get('deliveryHistory')
    if history is None:history=dict(records=[] if last is None else [last],earlierRecordsUnavailable=True,earlierRecordsPruned=False)
    else:history=dict(history,records=[receipt(item) for item in history['records']])
    result=dict(task,target=target,status='ended' if status=='inactive' else status,
        involvedSessionIds=task.get('involvedSessionIds',[] if target['kind']=='new' else [target['sessionId']]),deliveryHistory=history)
    if last is not None:result['lastDelivery']=last
    latest={key:item for key,item in history['records'][-1].items() if key!='prompt'} if history['records'] else None
    if not deep_equal(latest,last,strict=True):
        parser.issue([],message='Last delivery must match the latest saved delivery receipt');raise ScheduleSchemaError(parser.issues)
    return result


class _TaskSchema(SchemaValidator):
    safeParse=SchemaValidator.safe_parse


schedule_task_schema=_TaskSchema(parse_schedule_task)
schedule_domain=define_domain(dict(name='schedule',version=2,compatibleVersions=[1],tables=dict(tasks=domain_table(schedule_task_schema))))
scheduleTaskSchema=schedule_task_schema
scheduleDomain=schedule_domain
