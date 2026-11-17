"""Bounded RFC5545 recurrence over UTC or explicit local wall time."""
import math
import re

from dsh.cordis.text import trim_js
from dsh.core.session.json import FrozenDict
from dsh.javascript.rrule_enumerator import enumerate_wall
from dsh.util_time_instant import (canonicalize_time_zone,resolve_local_instant,epoch_of,EPOCH,
    MAX_FOUR_DIGIT_YEAR_MS,is_four_digit_year_instant,format_four_digit_year_instant,CalendarRangeError)
from dsh.util_time_calendar import local_epoch,calendar_date,calendar_days,day_parts,iso_weekday
from dsh.util_time_recurrence import RecurrenceInputError,parse_recurrence,recurrence_decision
from datetime import datetime,timedelta

DAY_MS=86400000
CYCLE_PERIODS=dict(MINUTELY=210379680,HOURLY=3506328,DAILY=146097,WEEKLY=20871,MONTHLY=4800,YEARLY=400)
CYCLE_MS=CYCLE_PERIODS['DAILY']*DAY_MS
LAST_RRULE_WALL_MS=253402300799000
WEEKDAYS=['MO','TU','WE','TH','FR','SA','SU']
SUPPORTED_PARTS=['FREQ','INTERVAL','COUNT','UNTIL','WKST','BYSECOND','BYMINUTE','BYHOUR','BYDAY','BYMONTHDAY','BYYEARDAY','BYWEEKNO','BYMONTH','BYSETPOS']
LIST_RANGES=dict(BYSECOND=(0,59),BYMINUTE=(0,59),BYHOUR=(0,23),BYMONTHDAY=(-31,31),BYYEARDAY=(-366,366),BYWEEKNO=(-53,53),BYMONTH=(1,12),BYSETPOS=(-366,366))
TIME_PARTS=['BYHOUR','BYMINUTE','BYSECOND']


def _error(reason,message,cause=None):raise RecurrenceInputError(reason,message,cause)
def _match(pattern,text):return re.fullmatch(pattern,text,re.ASCII) is not None


def _basic_time(field,text):
    year,month,day=int(text[:4]),int(text[4:6]),int(text[6:8]);hour,minute,second=int(text[9:11]),int(text[11:13]),int(text[13:15])
    message=field+' must be a real calendar date and time in years 0100 through 9999.'
    if year<100:_error('syntax',message)
    def check(value,minimum,maximum):
        if not minimum<=value<=maximum:_error('syntax',message,CalendarRangeError('value out of range: %d <= %d <= %d' % (minimum,value,maximum)))
    check(month,1,12)
    next_year,next_month=(year+1,1) if month==12 else (year,month+1)
    check(day,1,calendar_days(next_year,next_month,1)-calendar_days(year,month,1))
    check(hour,0,23);check(minute,0,59);check(second,0,59)
    try:return epoch_of(datetime(year,month,day,hour,minute,second))
    except ValueError as error:_error('syntax',message,error)


def _parse_start(line):
    if _match(r'DTSTART:\d{8}T\d{6}Z',line):return 'UTC',_basic_time('DTSTART',line[-16:-1])
    if not _match(r'DTSTART;TZID=[^:;]+:\d{8}T\d{6}',line):_error('syntax','DTSTART must use UTC with Z or a local date-time with an explicit TZID.')
    zone=canonicalize_time_zone(line[len('DTSTART;TZID='):-16])
    if zone['kind']=='rejected':_error('time_zone','TZID must be UTC or a valid IANA Area/Location name.',zone)
    return zone['timeZone'],_basic_time('DTSTART',line[-15:])


def _rule_parts(line):
    parts={}
    for component in line[len('RRULE:'):].split(';'):
        key,separator,text=component.partition('=')
        if not separator or not key or not text or key in parts:_error('syntax','RRULE fields must be non-empty and unique.')
        if key not in SUPPORTED_PARTS:_error('syntax','RRULE supports only '+', '.join(SUPPORTED_PARTS)+'.')
        parts[key]=text
    return parts


def _positive(text,maximum,message):
    if text is None:return None
    if not _match(r'\d+',text) or not 1<=int(text)<=maximum:_error('syntax',message)
    return int(text)


def _list_values(key,text,bounds):
    minimum,maximum=bounds;signed=minimum<0;values=[]
    for item in text.split(','):
        if not _match(r'[+-]?\d+' if signed else r'\d+',item) or not minimum<=int(item)<=maximum or signed and int(item)==0:
            _error('syntax','%s values must be integers from %d to %d%s.' % (key,minimum,maximum,', excluding 0' if signed else ''))
        values.append(int(item))
    if len(set(values))!=len(values):_error('syntax',key+' values must be unique.')
    return values


def _by_day(text):
    if text is None:return None
    selectors=text.split(',');seen=set();ordinals=0
    for selector in selectors:
        if not _match(r'(?:[+-]?(?:[1-9]|[1-4]\d|5[0-3]))?(?:MO|TU|WE|TH|FR|SA|SU)',selector):_error('syntax','BYDAY contains an invalid weekday selector.')
        ordinal=selector[:-2];seen.add((int(ordinal or '0'),selector[-2:]));ordinals+=bool(ordinal)
    if len(seen)!=len(selectors):_error('syntax','BYDAY values must be unique.')
    return dict(entries=len(selectors),ordinals=ordinals)


def _rule_values(parts):
    frequency=parts.get('FREQ')
    if frequency is None:_error('syntax','RRULE must contain FREQ.')
    if frequency=='SECONDLY':_error('density','FREQ=SECONDLY is not supported; occurrences must be at least 60 seconds apart.')
    if frequency not in CYCLE_PERIODS:_error('syntax','FREQ must be MINUTELY, HOURLY, DAILY, WEEKLY, MONTHLY, or YEARLY.')
    interval=_positive(parts.get('INTERVAL'),9007199254740991,'INTERVAL must be a positive safe integer.')
    count=_positive(parts.get('COUNT'),1000,'COUNT must be an integer from 1 to 1000; use UNTIL for a longer finite recurrence.')
    until=parts.get('UNTIL')
    if until is not None:
        if not _match(r'\d{8}T\d{6}Z',until):_error('syntax','UNTIL must be an absolute UTC date-time ending in Z.')
        until=_basic_time('UNTIL',until[:-1])
    week_start=parts.get('WKST','MO')
    if week_start not in WEEKDAYS:_error('syntax','WKST must be MO, TU, WE, TH, FR, SA, or SU.')
    lists={key:_list_values(key,parts[key],bounds) for key,bounds in LIST_RANGES.items() if key in parts}
    return dict(frequency=frequency,interval=interval or 1,count=count,until=until,weekStart=WEEKDAYS.index(week_start),lists=lists,byDay=_by_day(parts.get('BYDAY')))


def _check_combination(values):
    frequency=values['frequency'];lists=values['lists'];ordinals=(values['byDay'] or {}).get('ordinals',0)
    if values['count'] is not None and values['until'] is not None:_error('syntax','RRULE must not contain both COUNT and UNTIL.')
    if len(lists.get('BYSECOND',[0]))>1:_error('density','BYSECOND must contain one value; occurrences must be at least 60 seconds apart.')
    if frequency in ('MINUTELY','HOURLY') and (lists or values['byDay'] is not None):_error('syntax','FREQ='+frequency+' does not support BY rule parts; use FREQ=DAILY or FREQ=WEEKLY with BYHOUR and BYMINUTE.')
    for key in ['BYWEEKNO','BYYEARDAY']:
        if key in lists and frequency!='YEARLY':_error('syntax',key+' requires FREQ=YEARLY.')
    if 'BYMONTHDAY' in lists and frequency not in ('MONTHLY','YEARLY'):_error('syntax','BYMONTHDAY requires FREQ=MONTHLY or FREQ=YEARLY.')
    if ordinals>0 and frequency not in ('MONTHLY','YEARLY'):_error('syntax','BYDAY ordinals require FREQ=MONTHLY or FREQ=YEARLY.')
    if ordinals>0 and 'BYWEEKNO' in lists:_error('syntax','BYDAY ordinals cannot be combined with BYWEEKNO.')
    if 'BYSETPOS' in lists and len(lists)==1 and values['byDay'] is None:_error('syntax','BYSETPOS requires another BY rule part.')


def _by_day_days(by_day,per_weekday):return math.inf if by_day is None else by_day['ordinals']+per_weekday*(by_day['entries']-by_day['ordinals'])


def _period_days(values):
    lists=values['lists'];by_day=values['byDay'];frequency=values['frequency']
    def size(key):return len(lists[key]) if key in lists else math.inf
    if frequency in ('MINUTELY','HOURLY','DAILY'):return 1
    if frequency=='WEEKLY':return min(7,_by_day_days(by_day,1))
    if frequency=='MONTHLY':return min(31,size('BYMONTHDAY'),_by_day_days(by_day,5))
    if 'BYMONTH' not in lists:return min(366,size('BYYEARDAY'),12*size('BYMONTHDAY'),9*size('BYWEEKNO'),_by_day_days(by_day,53))
    months=len(lists['BYMONTH'])
    return min(31*months,size('BYYEARDAY'),months*size('BYMONTHDAY'),9*size('BYWEEKNO'),months*_by_day_days(by_day,5))


def _check_cost(values,reject_ineffective):
    times=math.prod(len(values['lists'].get(key,[0])) for key in TIME_PARTS);candidates=_period_days(values)*times
    if candidates>10080:_error('density','One FREQ period of this RRULE can contain up to %d occurrences; the limit is 10080.' % candidates)
    positions=values['lists'].get('BYSETPOS',[])
    if reject_ineffective and candidates==1 and positions:
        _error('syntax','BYSETPOS has no effect because one FREQ='+values['frequency']+' period of this RRULE contains at most 1 occurrence. BYSETPOS selects among the occurrences of one period; for example, FREQ=MONTHLY;BYDAY=MO,TU,WE,TH,FR;BYSETPOS=-1 selects the last weekday of each month.')
    if len(positions)>31:_error('syntax','BYSETPOS must contain at most 31 values.')
    if any(abs(position)>candidates for position in positions):_error('syntax','BYSETPOS values must be from 1 to %d or from -%d to -1; one FREQ period of this RRULE contains at most %d occurrences.' % (candidates,candidates,candidates))


def _start_defaults(values,start):
    defaults={};frequency=values['frequency'];lists=values['lists']
    if frequency in ('MINUTELY','HOURLY'):return defaults
    date=EPOCH+timedelta(milliseconds=start)
    for key,value in [('BYHOUR',date.hour),('BYMINUTE',date.minute),('BYSECOND',date.second)]:
        if key not in lists:defaults[key]=str(value)
    if values['byDay'] is not None or any(key in lists for key in ['BYMONTHDAY','BYYEARDAY','BYWEEKNO']):return defaults
    if frequency=='WEEKLY':defaults['BYDAY']=WEEKDAYS[date.weekday()]
    if frequency in ('MONTHLY','YEARLY'):defaults['BYMONTHDAY']=str(date.day)
    if frequency=='YEARLY' and 'BYMONTH' not in lists:defaults['BYMONTH']=str(date.month)
    return defaults


def _instant_of(wall,zone):
    year,month,day=calendar_date(wall//DAY_MS);clock=wall%DAY_MS
    parts=dict(year=year,month=month,day=day,hour=clock//3600000,minute=clock//60000%60,second=clock//1000%60,millisecond=0)
    return resolve_local_instant(parts,zone)


def prepare_rrule(value,reject_ineffective=False):
    lines=[trim_js(line) for line in trim_js(value.replace('\r\n','\n')).split('\n') if trim_js(line)]
    if len(lines)!=2 or not lines[0].startswith('DTSTART') or not lines[1].startswith('RRULE:'):_error('syntax','rrule must contain one DTSTART line followed by one RRULE line.')
    start_line,rule_line=lines;zone,start=_parse_start(start_line)
    if _instant_of(start,zone) is None:_error('syntax','DTSTART must be a real local date and time in its time zone.')
    parts=_rule_parts(rule_line);values=_rule_values(parts);_check_combination(values)
    recurrence_parts=dict(parts,**_start_defaults(values,start));recurrence_values=_rule_values(recurrence_parts);_check_cost(recurrence_values,reject_ineffective)
    recurrence_parts.pop('COUNT',None);recurrence_parts.pop('UNTIL',None)
    for key in TIME_PARTS:
        if key in recurrence_values['lists']:recurrence_parts[key]=','.join(str(item) for item in sorted(recurrence_values['lists'][key]))
    return dict(normalized=start_line+'\n'+rule_line,timeZone=zone,start=start,frequency=values['frequency'],interval=values['interval'],weekStart=values['weekStart'],count=values['count'],
        limit=MAX_FOUR_DIGIT_YEAR_MS if values['until'] is None else values['until'],recurrence='RRULE:'+';'.join(key+'='+text for key,text in recurrence_parts.items()),
        invalidRunLimit=CYCLE_MS*values['interval']//math.gcd(values['interval'],CYCLE_PERIODS[values['frequency']]))


def _period_start(prepared,wall):
    start=prepared['start'];interval=prepared['interval'];frequency=prepared['frequency']
    def floor(origin,value,step):return origin+math.floor((value-origin)/step)*step
    if frequency in ('MINUTELY','HOURLY'):return floor(start,wall,interval*(60000 if frequency=='MINUTELY' else 3600000))
    if frequency=='DAILY':return floor(start//DAY_MS,wall//DAY_MS,interval)*DAY_MS
    if frequency=='WEEKLY':
        def week(day):return day-(day+3-prepared['weekStart'])%7
        return floor(week(start//DAY_MS),week(wall//DAY_MS),7*interval)*DAY_MS
    start_date=calendar_date(start//DAY_MS);date=calendar_date(wall//DAY_MS)
    if frequency=='MONTHLY':
        month=floor(start_date[0]*12+start_date[1]-1,date[0]*12+date[1]-1,interval)
        return calendar_days(month//12,month%12+1,1)*DAY_MS
    return calendar_days(floor(start_date[0],date[0],interval),1,1)*DAY_MS


def _period_anchor(prepared,wall):return max(_period_start(prepared,wall),prepared['start']) if wall>prepared['start'] else prepared['start']


def _has_candidate(prepared):
    if prepared['frequency'] in ('MINUTELY','HOURLY'):return True
    first=_period_start(prepared,prepared['start']);first_year=calendar_date(first//DAY_MS)[0]
    cycle_years=400*prepared['interval']/math.gcd(prepared['interval'],CYCLE_PERIODS[prepared['frequency']])
    cycles=max(1 if first_year<100 else 0,math.floor((9999-first_year-cycle_years-1)/400))
    anchor=first+cycles*CYCLE_MS
    return enumerate_wall(prepared['recurrence'],anchor,anchor,mode='after') is not None


def _walls(prepared,from_wall,through):
    while from_wall<=LAST_RRULE_WALL_MS:
        # A fixed page includes lookahead beyond the decision: a future wall
        # value may be a gap, so it cannot terminate enumeration by itself.
        rows=enumerate_wall(prepared['recurrence'],_period_anchor(prepared,from_wall),from_wall,through=None)
        for wall in rows:yield wall
        if not rows or len(rows)<2048:return
        from_wall=rows[-1]+1


def _scan_window(prepared,from_wall,decision):
    window=dict(latest=None,next=None)
    if from_wall>LAST_RRULE_WALL_MS:return window
    bound=min(decision,prepared['limit']);bound_wall=local_epoch(bound,prepared['timeZone']);below=[];last_valid=bound_wall
    for wall in _walls(prepared,from_wall,bound_wall):
        if wall<=bound_wall:below.append(wall);continue
        if wall>=prepared['limit']+DAY_MS:break
        value=_instant_of(wall,prepared['timeZone'])
        if value is None:
            if wall-last_valid>prepared['invalidRunLimit']:break
            continue
        last_valid=wall
        if value<=bound:window['latest']=value;continue
        if value<=prepared['limit']:window['next']=value
        break
    while window['latest'] is None and below:
        value=_instant_of(below.pop(),prepared['timeZone'])
        if value is not None and value<=bound:window['latest']=value
    return window


def _dispatch_window(prepared,saved,decision):
    saved_wall=local_epoch(saved,prepared['timeZone']);bound_wall=local_epoch(min(decision,prepared['limit']),prepared['timeZone']);span=2*DAY_MS
    while True:
        from_wall=max(bound_wall-span,saved_wall);window=_scan_window(prepared,from_wall,decision)
        if window['latest'] is not None or from_wall==saved_wall:return window
        span*=2


def _count_window(prepared,decision,count):
    window=dict(latest=None,next=None);remaining=count;last_valid=prepared['start']
    # Count pages enumerate beyond the decision only until its first future item.
    for wall in _walls(prepared,prepared['start'],decision+DAY_MS):
        value=_instant_of(wall,prepared['timeZone'])
        if value is None:
            if wall-last_valid>prepared['invalidRunLimit']:break
            continue
        if value==window['latest']:continue
        last_valid=wall
        if value>decision:
            if value<=MAX_FOUR_DIGIT_YEAR_MS:window['next']=value
            break
        window['latest']=value;remaining-=1
        if remaining<=0:break
    return window


class RRule:
    __slots__=('_prepared',)
    def __init__(self,prepared):object.__setattr__(self,'_prepared',prepared)
    def __setattr__(self,name,value):raise TypeError('frozen RRULE')
    @property
    def expression(self):return self._prepared['normalized']
    @property
    def timeZone(self):return self._prepared['timeZone']
    @staticmethod
    def parse(expression,options=None):return parse_recurrence(lambda:RRule(prepare_rrule(expression,(options or {}).get('rejectIneffectiveSetPositions',False))))

    def next(self,after):
        if not is_four_digit_year_instant(after):raise CalendarRangeError('RRULE lower bound must be a four-digit-year instant')
        prepared=self._prepared
        if not _has_candidate(prepared):return None
        window=_scan_window(prepared,local_epoch(after,prepared['timeZone']),after) if prepared['count'] is None else _count_window(prepared,after,prepared['count'])
        return format_four_digit_year_instant(window['next']) if window['next'] is not None else None

    def resolve(self,scheduled_at,accepted_at):
        saved=recurrence_decision(scheduled_at,accepted_at);prepared=self._prepared
        window=_dispatch_window(prepared,saved,accepted_at) if prepared['count'] is None else _count_window(prepared,accepted_at,prepared['count'])
        result=dict(occurrenceAt=format_four_digit_year_instant(max(saved,window['latest'] if window['latest'] is not None else saved)))
        if window['next'] is not None:result['nextScheduledAt']=format_four_digit_year_instant(window['next'])
        return FrozenDict(result)
