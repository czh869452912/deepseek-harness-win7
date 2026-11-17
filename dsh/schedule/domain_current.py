"""Current Host reminder vocabulary; independent of historical Session logs."""
import math

from dsh.cordis.text import trim_js
from dsh.cordis.json_text import stringify_json
from dsh.core.session.json import FrozenDict
from dsh import util_time_instant as instant

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
