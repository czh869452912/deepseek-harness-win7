"""Typed current Schedule timing construction and descriptive/rule edits."""
from dsh.cordis.text import trim_js
from dsh.core.session.json import FrozenDict
from dsh.schedule import domain_current as domain
from dsh.cordis.utils import deep_equal

SELECTORS=dict(after='after_seconds',at='at',every='every_seconds',daily='daily',weekly='weekly',cron='cron',rrule='rrule')


def validate_timing(value):
    if not isinstance(value,dict) or not isinstance(value.get('kind'),str) or value['kind'] not in SELECTORS or set(value)!={'kind',SELECTORS[value['kind']]}:
        raise domain.ScheduleInputError('invalid_rule','timing must contain exactly kind and its matching selector.')
    return value


def create_schedule_record(id,title,prompt,value,now):
    timing=validate_timing(value);kind=timing['kind'];selector=timing[SELECTORS[kind]]
    if kind=='rrule':return domain.create_rrule_schedule_record(id,title,prompt,selector,now)
    constructor=dict(after=domain.create_after_schedule_record,at=domain.create_at_schedule_record,every=domain.create_every_schedule_record,
        daily=domain.create_daily_schedule_record,weekly=domain.create_weekly_schedule_record,cron=domain.create_cron_schedule_record)[kind]
    return constructor(id,prompt,selector,now,title)


def timing_of(record):
    kind=record['kind']
    if kind in ('after','at'):return dict(kind='at',at=record['scheduledAt'])
    if kind=='every':return dict(kind='every',every_seconds=record['everySeconds'])
    if kind in ('daily','weekly'):
        fields=dict(time=record['time'],time_zone=record['timeZone'])
        if kind=='weekly':fields['weekdays']=record['weekdays']
        return dict(kind=kind,**{kind:fields})
    if kind=='cron':return dict(kind=kind,cron=dict(expression=record['expression'],time_zone=record['timeZone']))
    return dict(kind='rrule',rrule=record['rrule'])


def normalized_timing(value):
    timing=validate_timing(value);kind=timing['kind']
    if kind=='after' or kind=='every':return timing
    if kind=='at':return dict(kind=kind,at=domain.parse_at_input(timing['at']))
    if kind=='rrule':return dict(kind=kind,rrule=domain.normalize_rrule(timing['rrule']))
    parser=dict(daily=domain.parse_daily_input,weekly=domain.parse_weekly_input,cron=domain.parse_cron_input)[kind]
    return dict(kind=kind,**parser(timing[kind]))


def update_schedule_record(current,patch,now,resume):
    title=domain.schedule_title(patch.get('title',current['title']));prompt=patch.get('prompt',current['prompt'])
    if not isinstance(prompt,str) or not trim_js(prompt):raise domain.ScheduleInputError('invalid_prompt','prompt must be non-empty after trimming.')
    timing=patch.get('timing',timing_of(current))
    changed='timing' in patch and not deep_equal(normalized_timing(timing),normalized_timing(timing_of(current)),strict=True)
    try:
        if current['kind']=='rrule' and timing['kind']=='rrule':
            change=dict(title=title,prompt=prompt)
            if changed:change['rrule']=timing['rrule']
            return domain.update_rrule_schedule_record(current,change,now,changed or resume)
        if changed or resume:return create_schedule_record(current['id'],title,prompt,timing,now)
    except domain.ScheduleInputError as error:
        if resume and not changed and error.code=='not_future':raise domain.ScheduleInputError('not_future','This task has no future occurrence. Set a future schedule before resuming it.') from error
        raise
    return current if title==current['title'] and trim_js(prompt)==current['prompt'] else FrozenDict(current,title=title,prompt=trim_js(prompt))


createScheduleRecord=create_schedule_record
updateScheduleRecord=update_schedule_record
