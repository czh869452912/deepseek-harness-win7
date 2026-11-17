"""Strict five-field Cron and bounded zone-aware latest/next decisions."""
import re

from dsh.cordis.text import trim_js,JS_WHITESPACE
from dsh.cordis.json_text import stringify_json
from dsh.core.session.json import FrozenDict,FrozenList
from dsh.util_time_instant import (canonicalize_time_zone,resolve_local_instant,is_four_digit_year_instant,
    format_four_digit_year_instant,MIN_FOUR_DIGIT_YEAR_MS,MAX_FOUR_DIGIT_YEAR_MS,CalendarRangeError)
from dsh.util_time_calendar import calendar_date,calendar_days,local_day,local_epoch,day_parts,iso_weekday
from dsh.util_time_recurrence import RecurrenceInputError,parse_recurrence,recurrence_decision

CRON_SEARCH_HORIZON_YEARS=400
FIELDS=[('minute',0,59,59),('hour',0,23,23),('day-of-month',1,31,31),('month',1,12,12),('day-of-week',0,7,6)]


def _invalid(spec,element):
    return RecurrenceInputError('syntax','cron.expression '+spec[0]+' field element '+stringify_json(element)+' must be *, a value, a-b, */n, a-b/n, or a comma-separated list of those.')


def _value(text,spec):
    value=int(text)
    if not spec[1]<=value<=spec[2]:raise RecurrenceInputError('syntax','cron.expression %s field value %s is outside %s-%s.' % (spec[0],text,spec[1],spec[2]))
    return value


def _step(text,spec):
    value=int(text)
    if not 1<=value<=9007199254740991:raise RecurrenceInputError('syntax','cron.expression '+spec[0]+' field step must be a positive integer.')
    return value


def _walk(spec,step):return sorted({spec[1] if spec[2]!=spec[3] and value==spec[2] else value for value in range(spec[1],spec[2]+1,step)})


def _values(raw,spec):
    matched=set()
    for element in raw.split(','):
        if not element:raise RecurrenceInputError('syntax','cron.expression '+spec[0]+' field must not contain an empty list element.')
        if element=='*':matched.update(range(spec[1],spec[2]+1));continue
        if element.startswith('*'):
            found=re.fullmatch(r'\*/(\d+)',element,re.ASCII)
            if found is None:raise _invalid(spec,element)
            matched.update(range(spec[1],spec[2]+1,_step(found[1],spec)));continue
        found=re.fullmatch(r'(\d+)(?:-(\d+))?(?:/(\d+))?',element,re.ASCII)
        if found is None:raise _invalid(spec,element)
        start=_value(found[1],spec);end=found[2];step=found[3]
        if end is None:
            if step is not None:raise _invalid(spec,element)
            matched.add(start);continue
        last=_value(end,spec)
        if start>last:raise RecurrenceInputError('syntax','cron.expression %s field range %s-%s is inverted.' % (spec[0],start,last))
        matched.update(range(start,last+1,1 if step is None else _step(step,spec)))
    return sorted({spec[1] if spec[3]!=spec[2] and value==spec[2] else value for value in matched})


def _encode(values):
    if len(values)==1:return str(values[0])
    step=values[1]-values[0]
    if all(values[index]-values[index-1]==step for index in range(2,len(values))):
        return '%d-%d%s' % (values[0],values[-1],'' if step==1 else '/'+str(step))
    parts=[];start=values[0]
    for index in range(1,len(values)):
        if values[index]==values[index-1]+1:continue
        previous=values[index-1];parts.append(str(start) if start==previous else '%d-%d' % (start,previous));start=values[index]
    last=values[-1];parts.append(str(start) if start==last else '%d-%d' % (start,last))
    return ','.join(parts)


def _encode_star(values,spec):
    if len(values)==spec[3]-spec[1]+1:return '*'
    best=[];best_step=None;present=set(values)
    for step in range(1,spec[2]-spec[1]+2):
        walk=_walk(spec,step)
        if len(walk)>len(best) and all(value in present for value in walk):best=walk;best_step=step
    remaining=[value for value in values if value not in best]
    return '*/'+str(best_step)+(','+_encode(remaining) if remaining else '')


def parse_cron_expression(expression):
    if not isinstance(expression,str) or not expression or trim_js(expression)!=expression:raise RecurrenceInputError('syntax','cron.expression must be a non-empty trimmed string.')
    fields=re.split('['+re.escape(JS_WHITESPACE)+']+',expression)
    if len(fields)!=5:raise RecurrenceInputError('syntax','cron.expression must contain exactly five whitespace-separated fields: minute hour day-of-month month day-of-week.')
    parsed=[_values(raw,spec) for raw,spec in zip(fields,FIELDS)]
    text=' '.join(_encode_star(values,spec) if raw.startswith('*') else _encode(values) for raw,values,spec in zip(fields,parsed,FIELDS))
    return FrozenDict(expression=text,minutes=FrozenList(parsed[0]),hours=FrozenList(parsed[1]),daysOfMonth=FrozenList(parsed[2]),
        months=FrozenList(parsed[3]),daysOfWeek=FrozenList(parsed[4]),dayOfMonthStar=fields[2].startswith('*'),dayOfWeekStar=fields[4].startswith('*'))


def _matches(parsed,day):
    _,month,date=calendar_date(day)
    if month not in parsed['months']:return False
    dom=date in parsed['daysOfMonth'];dow=iso_weekday(day)%7 in parsed['daysOfWeek']
    return dom or dow if not parsed['dayOfMonthStar'] and not parsed['dayOfWeekStar'] else dom and dow


def _year_shift(day,years):
    year,month,date=calendar_date(day);year+=years
    next_year,next_month=(year+1,1) if month==12 else (year,month+1)
    length=calendar_days(next_year,next_month,1)-calendar_days(year,month,1)
    return calendar_days(year,month,min(date,length))


def _target(day,minute,zone):
    return resolve_local_instant(day_parts(day,'%02d:%02d:00.000' % (minute//60,minute%60)),zone)


class Cron:
    __slots__=('_fields','_time_zone')
    def __init__(self,fields,time_zone):object.__setattr__(self,'_fields',fields);object.__setattr__(self,'_time_zone',time_zone)
    def __setattr__(self,name,value):raise TypeError('frozen Cron rule')
    @property
    def fields(self):return self._fields
    @property
    def timeZone(self):return self._time_zone
    @property
    def expression(self):return self.fields['expression']

    @staticmethod
    def parse(expression,time_zone):
        def parse():
            fields=parse_cron_expression(expression);zone=canonicalize_time_zone(time_zone)
            if zone['kind']=='rejected':raise RecurrenceInputError('time_zone','Cron requires a valid UTC or IANA Area/Location zone.',zone)
            return Cron(fields,zone['timeZone'])
        return parse_recurrence(parse)

    def _times(self):return [hour*60+minute for hour in self.fields['hours'] for minute in self.fields['minutes']]

    def next(self,after):
        if not is_four_digit_year_instant(after):raise CalendarRangeError('Cron lower bound must be a four-digit-year instant')
        wall=local_epoch(after,self.timeZone);first=wall//86400000;day=first;floor_minute=wall%86400000//60000
        last=min(_year_shift(day,400),calendar_days(10000,1,1));times=self._times()
        while day<=last:
            year,month,_=calendar_date(day)
            if month not in self.fields['months']:
                day=calendar_days(year+1,1,1) if month==12 else calendar_days(year,month+1,1);continue
            if _matches(self.fields,day):
                for minute in times:
                    if day==first and minute<floor_minute:continue
                    target=_target(day,minute,self.timeZone)
                    if target is None:continue
                    if target>MAX_FOUR_DIGIT_YEAR_MS:return None
                    if target>=MIN_FOUR_DIGIT_YEAR_MS and target>after:return format_four_digit_year_instant(target)
            day+=1
        return None

    def resolve(self,scheduled_at,accepted_at):
        saved=recurrence_decision(scheduled_at,accepted_at);day=local_day(accepted_at,'UTC')+1
        first=max(_year_shift(day,-400),local_day(MIN_FOUR_DIGIT_YEAR_MS,self.timeZone));times=self._times();occurrence=saved
        while day>=first:
            year,month,_=calendar_date(day)
            if month not in self.fields['months']:day=calendar_days(year,month,1)-1;continue
            if _matches(self.fields,day):
                earliest=next((target for target in (_target(day,minute,self.timeZone) for minute in times) if target is not None),None)
                if earliest is not None and earliest>accepted_at:day-=1;continue
                found=False
                for minute in reversed(times):
                    candidate=_target(day,minute,self.timeZone)
                    if candidate is None or candidate>accepted_at or candidate<MIN_FOUR_DIGIT_YEAR_MS:continue
                    occurrence=max(candidate,saved);found=True;break
                if found:break
            day-=1
        result=dict(occurrenceAt=format_four_digit_year_instant(occurrence));future=self.next(accepted_at)
        if future is not None:result['nextScheduledAt']=future
        return FrozenDict(result)
