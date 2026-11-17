"""Current Host reminder vocabulary; independent of historical Session logs."""
import math
import re

from dsh.cordis.text import trim_js
from dsh.cordis.json_text import stringify_json
from dsh.core.session.json import FrozenDict,FrozenList
from dsh import util_time_instant as instant
from dsh.util_time_calendar import local_day,local_epoch,day_parts,iso_weekday,calendar_days,calendar_date

MIN_EVERY_INTERVAL_SECONDS=60
MAX_TITLE_LENGTH=120
REQUIRED_TITLE_MESSAGE='title is required and must be non-empty after trimming.'
NON_CANONICAL_INSTANT_MESSAGE='scheduledAt must be a canonical four-digit-year RFC 3339 UTC instant'


class ScheduleLogError(ValueError):
    name='ScheduleLogError'
    code='corrupt_schedule_log'


class ScheduleInputError(ValueError):
    name='ScheduleInputError'
    def __init__(self,code,message,cause=None):
        self.code=code;self.cause=cause;super().__init__(message)


def safe_integer(value):
    return type(value) in (int,float) and -9007199254740991<=value<=9007199254740991 and math.isfinite(value) and value==int(value)


def text_length(value):return len(value.encode('utf-16-le','surrogatepass'))//2


def schedule_title(title):
    if not isinstance(title,str) or not trim_js(title):raise ScheduleInputError('invalid_prompt',REQUIRED_TITLE_MESSAGE)
    normalized=trim_js(title)
    if text_length(normalized)>MAX_TITLE_LENGTH:raise ScheduleInputError('invalid_prompt','title must be at most 120 characters.')
    return normalized


def decode_stored_title(value):
    if not isinstance(value,str) or not trim_js(value):raise ScheduleLogError(REQUIRED_TITLE_MESSAGE)
    if text_length(value)>MAX_TITLE_LENGTH:raise ScheduleLogError('title must be at most 120 characters')
    if trim_js(value)!=value:raise ScheduleLogError('title must be a trimmed string')
    return value


def decode_id(value):
    if not isinstance(value,str) or not value or trim_js(value)!=value:
        raise ScheduleLogError('schedule id must be a non-empty string without surrounding whitespace')
    return value


def decode_instant(value):
    if not isinstance(value,str):raise ScheduleLogError(NON_CANONICAL_INSTANT_MESSAGE)
    parsed=instant.four_digit_year_epoch(value)
    if parsed['kind']=='rejected':
        raise ScheduleLogError('scheduledAt is not a real UTC calendar instant' if parsed['reason']=='not_a_calendar_date' else NON_CANONICAL_INSTANT_MESSAGE)
    return value


def canonicalize_time_zone(value):
    resolved=instant.canonicalize_time_zone(value)
    if resolved['kind']=='rejected':
        message='time_zone must resolve to UTC or an IANA Area/Location name.' if resolved['reason']=='not_canonical_shape' else 'time_zone must be UTC or a valid IANA Area/Location name.'
        raise ScheduleInputError('invalid_time_zone',message,resolved.get('cause'))
    return resolved['timeZone']


def future_instant(epoch,now):
    formatted=instant.format_four_digit_year_instant(epoch)
    if not safe_integer(now) or formatted is None:
        raise ScheduleInputError('time_out_of_range','The scheduled time must be representable as a four-digit-year RFC 3339 UTC instant.')
    if epoch<=now:raise ScheduleInputError('not_future','The scheduled time must be strictly in the future.')
    return formatted


def parse_at_input(at):
    if isinstance(at,str):
        parsed=instant.parse_offset_instant(at)
        if parsed['kind']=='accepted':return parsed['epoch']
        messages={
            'not_rfc3339':'at must use YYYY-MM-DDTHH:mm:ss with optional 1-3 digit fractional seconds and an explicit Z or numeric offset.',
            'invalid_numeric_offset':'The at numeric offset is invalid.'}
        raise ScheduleInputError('invalid_rule',messages.get(parsed['reason'],'The at value must be a real ISO calendar date and time.'))
    if not isinstance(at,dict):raise ScheduleInputError('invalid_rule','at must be an explicit-offset string or local calendar object.')
    if set(at)!={'date','time','time_zone'}:raise ScheduleInputError('invalid_rule','Local at must contain exactly date, time, and time_zone.')
    if not isinstance(at['date'],str) or not isinstance(at['time'],str):raise ScheduleInputError('invalid_rule','Local at date and time must be strings.')
    if not isinstance(at['time_zone'],str):raise ScheduleInputError('invalid_time_zone','time_zone must be a string.')
    parsed=instant.parse_local_calendar(at['date'],at['time'])
    if parsed['kind']=='rejected':
        messages={'malformed':'Local at requires date YYYY-MM-DD and time HH:mm:ss with optional one-to-three digit milliseconds.',
            'not_a_calendar_date':'The at value must be a real ISO calendar date and time.',
            'out_of_range':'The local at value must be a real ISO calendar date and time.'}
        raise ScheduleInputError('invalid_rule',messages[parsed['reason']])
    target=instant.resolve_local_instant(parsed['time'],canonicalize_time_zone(at['time_zone']))
    if target is None:raise ScheduleInputError('invalid_rule','The local at time does not exist in the selected time zone.')
    return target


def _prompt(prompt):
    normalized=trim_js(prompt)
    if not normalized:raise ScheduleInputError('invalid_prompt','prompt must be non-empty after trimming.')
    return normalized


def create_after_schedule_record(id,prompt,after_seconds,now,title):
    prompt=_prompt(prompt)
    if not safe_integer(after_seconds) or after_seconds<=0:raise ScheduleInputError('invalid_rule','after_seconds must be a positive safe integer.')
    return FrozenDict(id=id,kind='after',title=schedule_title(title),prompt=prompt,afterSeconds=after_seconds,
        scheduledAt=future_instant(now+after_seconds*1000,now))


def create_at_schedule_record(id,prompt,at,now,title):
    prompt=_prompt(prompt)
    return FrozenDict(id=id,kind='at',title=schedule_title(title),prompt=prompt,scheduledAt=future_instant(parse_at_input(at),now))


def create_every_schedule_record(id,prompt,every_seconds,now,title):
    prompt=_prompt(prompt)
    if not safe_integer(every_seconds):raise ScheduleInputError('invalid_rule','every_seconds must be a safe integer.')
    if every_seconds<MIN_EVERY_INTERVAL_SECONDS:raise ScheduleInputError('frequency_too_high','every_seconds must be at least 60.')
    return FrozenDict(id=id,kind='every',title=schedule_title(title),prompt=prompt,everySeconds=every_seconds,
        scheduledAt=future_instant(now+every_seconds*1000,now))


def decode_interval_record(value):
    """Decode after/at/every records without recalculating a committed target."""
    if not isinstance(value,dict):raise ScheduleLogError('schedule record must be an object')
    kind=value.get('kind')
    if kind not in ('after','at','every'):raise ScheduleLogError('schedule kind must be "after", "at", "every", "daily", "weekly", "cron", or "rrule"')
    title=decode_stored_title(value.get('title'))
    keys=['id','kind','title','prompt']+([] if kind=='at' else ['afterSeconds' if kind=='after' else 'everySeconds'])+['scheduledAt']
    if set(value)!=set(keys):raise ScheduleLogError(kind+' schedule must contain exactly '+', '.join(keys[:-1])+', and scheduledAt')
    prompt=value['prompt']
    if not isinstance(prompt,str) or not prompt or trim_js(prompt)!=prompt:raise ScheduleLogError(kind+' prompt must be non-empty and already trimmed')
    fields={}
    if kind=='after':
        seconds=value['afterSeconds']
        if not safe_integer(seconds) or seconds<=0:raise ScheduleLogError('afterSeconds must be a positive safe integer')
        fields['afterSeconds']=seconds
    elif kind=='every':
        seconds=value['everySeconds']
        if not safe_integer(seconds) or seconds<60 or not safe_integer(seconds*1000):raise ScheduleLogError('everySeconds must be a safe integer of at least 60')
        fields['everySeconds']=seconds
    return FrozenDict(id=decode_id(value['id']),kind=kind,title=title,prompt=prompt,scheduledAt=decode_instant(value['scheduledAt']),**fields)


def resolve_every_occurrence(record,accepted_at):
    target=instant.four_digit_year_epoch(record['scheduledAt'])['epoch'];interval=record['everySeconds']*1000
    if not instant.is_four_digit_year_instant(accepted_at):raise ScheduleLogError('every acceptedAt must be a representable four-digit-year instant')
    if not safe_integer(interval) or interval<=0:raise ScheduleLogError('every interval milliseconds must be a positive safe integer')
    if accepted_at<target:raise ScheduleLogError('every dispatch cannot precede the active scheduledAt')
    occurrence=target+math.floor((accepted_at-target)/interval)*interval
    if not safe_integer(occurrence) or occurrence<target or occurrence>accepted_at:raise ScheduleLogError('every occurrence arithmetic must stay within the accepted interval')
    result=dict(occurrenceAt=instant.format_four_digit_year_instant(occurrence))
    next_target=occurrence+interval
    if instant.is_four_digit_year_instant(next_target):result['nextScheduledAt']=instant.format_four_digit_year_instant(next_target)
    return FrozenDict(result)


def render_reminder_framing(record):
    return '\n'.join(['[SCHEDULE REMINDER]','This is a scheduled message from the user',
        'schedule_id_json: '+stringify_json(record['id']),'occurrence_at: '+record['scheduledAt'],
        'reminder_prompt_json: '+stringify_json(record['prompt'])])


def render_recurring_reminder_batch_framing(reminders):
    payload=[dict(schedule_id=row['record']['id'],occurrence_at=row['occurrenceAt'],reminder_prompt=row['record']['prompt']) for row in reminders]
    return '\n'.join(['[SCHEDULE REMINDER BATCH]','This is a scheduled message from the user','reminders_json: '+stringify_json(payload)])


scheduleTitle=schedule_title
decodeStoredTitle=decode_stored_title
decodeId=decode_id
decodeInstant=decode_instant
canonicalizeTimeZone=canonicalize_time_zone
futureInstant=future_instant
parseAtInput=parse_at_input
createAfterScheduleRecord=create_after_schedule_record
createAtScheduleRecord=create_at_schedule_record
createEveryScheduleRecord=create_every_schedule_record
resolveEveryOccurrence=resolve_every_occurrence
renderReminderFraming=render_reminder_framing
renderRecurringReminderBatchFraming=render_recurring_reminder_batch_framing


LOCAL_CLOCK_TIME=re.compile(r'(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d(?:\.\d{1,3})?\Z',re.ASCII)


def local_clock_time(value,selector):
    if LOCAL_CLOCK_TIME.fullmatch(value) is None:
        raise ScheduleInputError('invalid_rule',selector+'.time must use HH:mm:ss with optional 1-3 fractional digits, without leap seconds or 24:00.')
    clock,_,fraction=value.partition('.')
    return clock+'.'+fraction.ljust(3,'0')


def normalize_weekdays(weekdays):
    if not isinstance(weekdays,list) or not weekdays:raise ScheduleInputError('invalid_rule','weekly.weekdays must be a non-empty array of ISO weekday numbers.')
    unique=set()
    for weekday in weekdays:
        if not safe_integer(weekday) or not 1<=weekday<=7:raise ScheduleInputError('invalid_rule','Each weekly.weekdays entry must be an integer from 1 (Monday) through 7 (Sunday).')
        if weekday in unique:raise ScheduleInputError('invalid_rule','weekly.weekdays must not repeat weekday %d.' % weekday)
        unique.add(weekday)
    return FrozenList(sorted(unique))


def _parse_wall_input(value,selector):
    weekly=selector=='weekly';keys={'time','time_zone','weekdays'} if weekly else {'time','time_zone'}
    if not isinstance(value,dict) or set(value)!=keys or not isinstance(value.get('time'),str):
        fields='time, time_zone, and weekdays' if weekly else 'time and time_zone'
        raise ScheduleInputError('invalid_rule',selector+' must contain exactly '+fields+', with time HH:mm:ss and optional 1-3 fractional digits.')
    if not isinstance(value['time_zone'],str):raise ScheduleInputError('invalid_time_zone','time_zone must be a string.')
    result=dict(time=local_clock_time(value['time'],selector),timeZone=canonicalize_time_zone(value['time_zone']))
    if weekly:result['weekdays']=normalize_weekdays(value['weekdays'])
    return result


def parse_daily_input(value):return _parse_wall_input(value,'daily')
def parse_weekly_input(value):return _parse_wall_input(value,'weekly')


def next_wall_target(time,time_zone,now,weekdays=None,after_day=None):
    day=local_day(now,time_zone);last_day=calendar_days(10000,1,1)
    if after_day is not None and day<=after_day:day=after_day+1
    while day<=last_day:
        if weekdays is None or iso_weekday(day) in weekdays:
            target=instant.resolve_local_instant(day_parts(day,time),time_zone)
            if target is not None:
                if target>instant.MAX_FOUR_DIGIT_YEAR_MS:return None
                if target>=instant.MIN_FOUR_DIGIT_YEAR_MS and target>now:return instant.format_four_digit_year_instant(target)
        day+=1
    return None


def _create_wall_record(id,prompt,value,now,title,selector):
    prompt=_prompt(prompt);parsed=_parse_wall_input(value,selector);name=selector.capitalize()
    if not instant.is_four_digit_year_instant(now):raise ScheduleInputError('time_out_of_range',name+' creation time must be a representable four-digit-year UTC instant.')
    target=next_wall_target(parsed['time'],parsed['timeZone'],now,parsed.get('weekdays'))
    if target is None:raise ScheduleInputError('time_out_of_range','No future '+selector+' occurrence is representable as a four-digit-year UTC instant.')
    return FrozenDict(id=id,kind=selector,title=schedule_title(title),prompt=prompt,scheduledAt=target,**parsed)


def create_daily_schedule_record(id,prompt,daily,now,title):return _create_wall_record(id,prompt,daily,now,title,'daily')
def create_weekly_schedule_record(id,prompt,weekly,now,title):return _create_wall_record(id,prompt,weekly,now,title,'weekly')


def accepted_decision(selector,accepted_at):
    if not instant.is_four_digit_year_instant(accepted_at):raise ScheduleLogError(selector+' acceptedAt must be a representable four-digit-year instant')
    return accepted_at


def _resolve_wall_occurrence(record,accepted_at,selector):
    decision=accepted_decision(selector,accepted_at);saved=instant.four_digit_year_epoch(record['scheduledAt'])['epoch']
    if decision<saved:raise ScheduleLogError(selector+' dispatch cannot precede the active scheduledAt')
    time=local_clock_time(record['time'],selector)
    weekdays=normalize_weekdays(record['weekdays']) if selector=='weekly' else None
    day=local_day(decision,'UTC')+1
    while True:
        if weekdays is None or iso_weekday(day) in weekdays:
            candidate=instant.resolve_local_instant(day_parts(day,time),record['timeZone'])
            if candidate is not None and candidate<=decision:
                occurrence=max(candidate,saved);break
        day-=1
    result=dict(occurrenceAt=instant.format_four_digit_year_instant(occurrence))
    target=next_wall_target(time,record['timeZone'],decision,weekdays,local_day(occurrence,record['timeZone']))
    if target is not None:result['nextScheduledAt']=target
    return FrozenDict(result)


def resolve_daily_occurrence(record,accepted_at):return _resolve_wall_occurrence(record,accepted_at,'daily')
def resolve_weekly_occurrence(record,accepted_at):return _resolve_wall_occurrence(record,accepted_at,'weekly')


def decode_wall_record(value):
    """Validate a committed daily/weekly record without re-arming it."""
    if not isinstance(value,dict):raise ScheduleLogError('schedule record must be an object')
    kind=value.get('kind')
    if kind not in ('daily','weekly'):raise ScheduleLogError('Expected a daily or weekly schedule record')
    title=decode_stored_title(value.get('title'))
    keys=['id','kind','title','prompt','time','timeZone']+(['weekdays'] if kind=='weekly' else [])+['scheduledAt']
    if set(value)!=set(keys):raise ScheduleLogError(kind+' schedule must contain exactly '+', '.join(keys[:-1])+', and scheduledAt')
    prompt=value['prompt'];time=value['time'];zone=value['timeZone']
    if not isinstance(prompt,str) or not prompt or trim_js(prompt)!=prompt:raise ScheduleLogError(kind+' prompt must be non-empty and already trimmed')
    if not isinstance(time,str) or not isinstance(zone,str):raise ScheduleLogError(kind+' time and timeZone must be strings')
    try:
        if kind=='weekly':canonicalize_time_zone(zone)
        normalized=local_clock_time(time,kind)
        if kind=='daily':canonicalize_time_zone(zone)
    except ScheduleInputError as error:raise ScheduleLogError(error.name+': '+str(error)) from error
    if time!=normalized:raise ScheduleLogError(kind+' time must be normalized to HH:mm:ss.SSS')
    fields={}
    if kind=='weekly':
        try:weekdays=normalize_weekdays(value['weekdays'])
        except ScheduleInputError as error:raise ScheduleLogError(error.name+': '+str(error)) from error
        if weekdays!=value['weekdays']:raise ScheduleLogError('weekly weekdays must be normalized to unique ascending ISO weekday numbers')
        fields['weekdays']=weekdays
    return FrozenDict(id=decode_id(value['id']),kind=kind,title=title,prompt=prompt,time=time,timeZone=zone,scheduledAt=decode_instant(value['scheduledAt']),**fields)


normalizeWeekdays=normalize_weekdays
parseDailyInput=parse_daily_input
parseWeeklyInput=parse_weekly_input
createDailyScheduleRecord=create_daily_schedule_record
createWeeklyScheduleRecord=create_weekly_schedule_record
acceptedDecision=accepted_decision
resolveDailyOccurrence=resolve_daily_occurrence
resolveWeeklyOccurrence=resolve_weekly_occurrence


def read_recurrence(result):
    if result['kind']=='accepted':return result['rule']
    codes=dict(syntax='invalid_rule',time_zone='invalid_time_zone',density='frequency_too_high')
    raise ScheduleInputError(codes[result['reason']],result['detail'],result.get('cause'))


def canonicalize_cron_expression(expression):
    from dsh.util_time_cron import Cron
    return read_recurrence(Cron.parse(expression,'UTC')).expression


def parse_cron_input(value):
    if not isinstance(value,dict) or set(value)!={'expression','time_zone'} or not isinstance(value['expression'],str):
        raise ScheduleInputError('invalid_rule','cron must contain exactly expression and time_zone, with a five-field cron expression.')
    if not isinstance(value['time_zone'],str):raise ScheduleInputError('invalid_time_zone','time_zone must be a string.')
    return dict(expression=canonicalize_cron_expression(value['expression']),timeZone=canonicalize_time_zone(value['time_zone']))


def create_cron_schedule_record(id,prompt,cron,now,title):
    from dsh.util_time_cron import Cron
    prompt=_prompt(prompt);parsed=parse_cron_input(cron)
    if not instant.is_four_digit_year_instant(now):raise ScheduleInputError('time_out_of_range','Cron creation time must be a representable four-digit-year UTC instant.')
    target=read_recurrence(Cron.parse(parsed['expression'],parsed['timeZone'])).next(now)
    if target is None:raise ScheduleInputError('time_out_of_range','No future cron occurrence is representable as a four-digit-year UTC instant.')
    return FrozenDict(id=id,kind='cron',title=schedule_title(title),prompt=prompt,scheduledAt=target,**parsed)


def resolve_cron_occurrence(record,accepted_at):
    from dsh.util_time_cron import Cron
    accepted_decision('cron',accepted_at)
    if accepted_at<instant.four_digit_year_epoch(record['scheduledAt'])['epoch']:raise ScheduleLogError('cron dispatch cannot precede the active scheduledAt')
    return read_recurrence(Cron.parse(record['expression'],record['timeZone'])).resolve(record['scheduledAt'],accepted_at)


def decode_cron_record(value):
    if not isinstance(value,dict):raise ScheduleLogError('schedule record must be an object')
    title=decode_stored_title(value.get('title'))
    if set(value)!={'id','kind','title','prompt','expression','timeZone','scheduledAt'}:
        raise ScheduleLogError('cron schedule must contain exactly id, kind, title, prompt, expression, timeZone, and scheduledAt')
    prompt=value['prompt'];expression=value['expression'];zone=value['timeZone']
    if not isinstance(prompt,str) or not prompt or trim_js(prompt)!=prompt:raise ScheduleLogError('cron prompt must be non-empty and already trimmed')
    if not isinstance(expression,str) or not isinstance(zone,str):raise ScheduleLogError('cron expression and timeZone must be strings')
    try:canonicalize_time_zone(zone);canonical=canonicalize_cron_expression(expression)
    except ScheduleInputError as error:raise ScheduleLogError(error.name+': '+str(error)) from error
    if canonical!=expression:raise ScheduleLogError('cron expression must be canonical')
    return FrozenDict(id=decode_id(value['id']),kind='cron',title=title,prompt=prompt,expression=expression,timeZone=zone,scheduledAt=decode_instant(value['scheduledAt']))


canonicalizeCronExpression=canonicalize_cron_expression
parseCronInput=parse_cron_input
createCronScheduleRecord=create_cron_schedule_record
resolveCronOccurrence=resolve_cron_occurrence


def _first_rrule_record(id,title,prompt,prepared,now):
    if not instant.is_four_digit_year_instant(now):raise ScheduleInputError('time_out_of_range','The recurrence reference time is outside the supported range.')
    target=prepared.next(now)
    if target is None:raise ScheduleInputError('not_future','rrule must contain an occurrence strictly in the future.')
    return FrozenDict(id=id,kind='rrule',title=title,prompt=prompt,rrule=prepared.expression,scheduledAt=target)


def normalize_rrule(value):
    from dsh.util_time_rrule import RRule
    return read_recurrence(RRule.parse(value)).expression


def create_rrule_schedule_record(id,title,prompt,rrule,now):
    from dsh.util_time_rrule import RRule
    title=schedule_title(title);prompt=_prompt(prompt)
    prepared=read_recurrence(RRule.parse(rrule,dict(rejectIneffectiveSetPositions=True)))
    return _first_rrule_record(id,title,prompt,prepared,now)


def update_rrule_schedule_record(current,change,now,recompute):
    from dsh.util_time_rrule import RRule
    title=schedule_title(current['title'] if change.get('title') is None else change['title'])
    prompt=_prompt(current['prompt'] if change.get('prompt') is None else change['prompt'])
    prepared=read_recurrence(RRule.parse(change['rrule'],dict(rejectIneffectiveSetPositions=True)) if 'rrule' in change else RRule.parse(current['rrule']))
    if recompute:return _first_rrule_record(current['id'],title,prompt,prepared,now)
    return FrozenDict(current,title=title,prompt=prompt,rrule=prepared.expression)


def resolve_rrule_occurrence(record,accepted_at):
    from dsh.util_time_rrule import RRule
    decision=accepted_decision('rrule',accepted_at)
    if decision<instant.four_digit_year_epoch(record['scheduledAt'])['epoch']:raise ScheduleLogError('rrule dispatch cannot precede the active scheduledAt')
    return read_recurrence(RRule.parse(record['rrule'])).resolve(record['scheduledAt'],decision)


def decode_rrule_schedule_record(value):
    if not isinstance(value,dict) or value.get('kind')!='rrule' or set(value)!={'id','kind','title','prompt','rrule','scheduledAt'}:
        raise ScheduleLogError('rrule schedule must contain exactly id, kind, title, prompt, rrule, and scheduledAt')
    title=decode_stored_title(value['title']);prompt=value['prompt'];rrule=value['rrule']
    if not isinstance(prompt,str) or not prompt or trim_js(prompt)!=prompt:raise ScheduleLogError('schedule prompt must be non-empty and already trimmed')
    if not isinstance(rrule,str):raise ScheduleLogError('schedule rrule must be a string')
    try:normalized=normalize_rrule(rrule)
    except ScheduleInputError as error:raise ScheduleLogError('invalid schedule rrule: '+error.name+': '+str(error)) from error
    if normalized!=rrule:raise ScheduleLogError('schedule rrule must be normalized')
    return FrozenDict(id=decode_id(value['id']),kind='rrule',title=title,prompt=prompt,rrule=rrule,scheduledAt=decode_instant(value['scheduledAt']))


def decode_schedule_record(value):
    if not isinstance(value,dict):raise ScheduleLogError('schedule record must be an object')
    kind=value.get('kind')
    if kind in ('daily','weekly'):return decode_wall_record(value)
    if kind=='cron':return decode_cron_record(value)
    if kind=='rrule':return decode_rrule_schedule_record(value)
    return decode_interval_record(value)


def is_recurring_schedule_record(record):return record['kind'] in ('every','daily','weekly','cron','rrule')


def resolve_recurring_occurrence(record,accepted_at):
    return dict(every=resolve_every_occurrence,daily=resolve_daily_occurrence,weekly=resolve_weekly_occurrence,cron=resolve_cron_occurrence,rrule=resolve_rrule_occurrence)[record['kind']](record,accepted_at)


def format_schedule_local_time(record,value):
    from dsh.util_time_rrule import RRule
    zone=read_recurrence(RRule.parse(record['rrule'])).timeZone if record['kind']=='rrule' else record.get('timeZone','UTC')
    epoch=instant.parse_offset_instant(value)['epoch'];wall=local_epoch(epoch,zone);year,month,day=calendar_date(wall//86400000)
    clock=wall%86400000;offset=(wall-epoch)//1000
    date_year='%04d' % year if 0<=year<=9999 else '%+07d' % year
    rendered='%s-%02d-%02dT%02d:%02d:%02d' % (date_year,month,day,clock//3600000,clock//60000%60,clock//1000%60)
    # Temporal prints the actual local second but rounds the offset display to
    # the nearest minute (halfExpand), including historical second offsets.
    minutes=(abs(offset)+30)//60;suffix='%02d:%02d' % (minutes//60,minutes%60)
    return rendered+('+' if offset>=0 else '-')+suffix


normalizeRRule=normalize_rrule
createRRuleScheduleRecord=create_rrule_schedule_record
updateRRuleScheduleRecord=update_rrule_schedule_record
resolveRRuleOccurrence=resolve_rrule_occurrence
decodeRRuleScheduleRecord=decode_rrule_schedule_record
decodeScheduleRecord=decode_schedule_record
isRecurringScheduleRecord=is_recurring_schedule_record
resolveRecurringOccurrence=resolve_recurring_occurrence
formatScheduleLocalTime=format_schedule_local_time
