"""Current strict instant/calendar seam used by durable reminder records.

Epoch arithmetic avoids Windows CRT timestamp limits. Zone identity follows
the pinned ICU vocabulary; offset transitions use the bundled IANA database.
"""
import math
import re
from datetime import datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo

from dsh.cordis.text import trim_js
from dsh.cordis.utils import js_to_string
from dsh.util_time import IANA_TIME_ZONE,_zones

MIN_FOUR_DIGIT_YEAR_MS=-62135596800000
MAX_FOUR_DIGIT_YEAR_MS=253402300799999
EPOCH=datetime(1970,1,1)
def _regexp(pattern):
    # Without multiline mode JavaScript requires the actual end of input.
    # Python's $ additionally permits a final LF, so use its strict \Z anchor.
    return re.compile(pattern[:-1]+r'\Z',re.ASCII)


UTC_INSTANT=_regexp(r'^(?!0000)\d{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])T(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d\.\d{3}Z$')
LOCAL_DATE=_regexp(r'^(\d{4})-(\d{2})-(\d{2})$')
LOCAL_TIME=_regexp(r'^(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,3}))?$')
OFFSET_INSTANT=_regexp(r'^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,3}))?(Z|([+-])(\d{2}):(\d{2}))$')


class TimeZoneRangeError(ValueError):
    name='RangeError'
    def __init__(self,value):
        self.message='Invalid time zone specified: '+str(value)
        super().__init__(self.message)


class CalendarRangeError(ValueError):
    name='RangeError'


def rejected(reason):return dict(kind='rejected',reason=reason)


def epoch_of(value):
    delta=value-EPOCH
    return delta.days*86400000+delta.seconds*1000+delta.microseconds//1000


def _parts(groups):
    values=[int(value) for value in groups[:6]]
    values.append(int((groups[6] or '').ljust(3,'0') or '0'))
    return dict(zip(('year','month','day','hour','minute','second','millisecond'),values))


def _datetime(parts):
    return datetime(*(parts[key] for key in ('year','month','day','hour','minute','second')),microsecond=parts['millisecond']*1000)


def parse_local_calendar(date,time):
    date_match=LOCAL_DATE.match(js_to_string(date));time_match=LOCAL_TIME.match(js_to_string(time))
    if date_match is None or time_match is None:return rejected('malformed')
    parts=_parts(date_match.groups()+time_match.groups())
    if parts['year']==0 or parts['hour']>23 or parts['minute']>59 or parts['second']>59:return rejected('out_of_range')
    try:_datetime(parts)
    except ValueError:return rejected('not_a_calendar_date')
    return dict(kind='accepted',time=parts)


def parse_offset_instant(value):
    match=OFFSET_INSTANT.match(js_to_string(value))
    if match is None:return rejected('not_rfc3339')
    groups=match.groups();parts=_parts(groups)
    if parts['year']==0 or parts['hour']>23 or parts['minute']>59 or parts['second']>59:return rejected('out_of_range')
    try:epoch=epoch_of(_datetime(parts))
    except ValueError:return rejected('not_a_calendar_date')
    if groups[7]=='Z':return dict(kind='accepted',epoch=epoch)
    hour,minute=int(groups[9]),int(groups[10])
    if hour>23 or minute>59 or groups[8]=='-' and hour==0 and minute==0:return rejected('invalid_numeric_offset')
    return dict(kind='accepted',epoch=epoch-(1 if groups[8]=='+' else -1)*(hour*60+minute)*60000)


def is_four_digit_year_instant(epoch):
    return type(epoch) in (int,float) and MIN_FOUR_DIGIT_YEAR_MS<=epoch<=MAX_FOUR_DIGIT_YEAR_MS and math.isfinite(epoch) and epoch==int(epoch)


def format_four_digit_year_instant(epoch):
    if not is_four_digit_year_instant(epoch):return None
    value=EPOCH+timedelta(milliseconds=int(epoch))
    return '%04d-%02d-%02dT%02d:%02d:%02d.%03dZ' % (value.year,value.month,value.day,value.hour,value.minute,value.second,value.microsecond//1000)


def four_digit_year_epoch(value):
    text=js_to_string(value)
    if UTC_INSTANT.match(text) is None:return rejected('not_rfc3339')
    parsed=parse_offset_instant(text)
    if parsed['kind']=='rejected' or format_four_digit_year_instant(parsed['epoch'])!=value:return rejected('not_a_calendar_date')
    return parsed


def canonicalize_time_zone(value):
    if not isinstance(value,str):raise TypeError('time zone must be a string')
    if not value:return rejected('blank')
    if trim_js(value)!=value:return rejected('padded')
    if value!='UTC' and IANA_TIME_ZONE.fullmatch(value) is None:return rejected('not_area_location')
    canonical=_zones().get(value.lower())
    if canonical is None:return dict(kind='rejected',reason='unsupported',cause=TimeZoneRangeError(value))
    if canonical!='UTC' and IANA_TIME_ZONE.fullmatch(canonical) is None:return rejected('not_canonical_shape')
    return dict(kind='accepted',timeZone=canonical)


def _calendar_days(year,month,day):
    """Proleptic Gregorian epoch days, including Temporal's extended years."""
    year-=month<=2
    era=year//400;year_of_era=year-era*400
    day_of_year=(153*(month+(-3 if month>2 else 9))+2)//5+day-1
    return era*146097+year_of_era*365+year_of_era//4-year_of_era//100+day_of_year-719468


def resolve_local_instant(parts,time_zone):
    year=parts['year'];mapped=dict(parts)
    # ZoneInfo's future POSIX rules repeat with the Gregorian 400-year cycle.
    # Before year 1 its first (pre-transition) offset remains in force.
    mapped['year']=year if 1<=year<=9999 else 9600+year%400 if year>9999 else 400+year%400
    try:local=_datetime(mapped);zone=ZoneInfo(time_zone)
    except (ValueError,KeyError) as error:raise CalendarRangeError(str(error)) from error
    local_epoch=(_calendar_days(year,parts['month'],parts['day'])*86400000
        +parts['hour']*3600000+parts['minute']*60000+parts['second']*1000+parts['millisecond'])
    candidates=[]
    for fold in (0,1):
        offset=local.replace(tzinfo=zone,fold=fold).utcoffset()
        epoch=local_epoch-int(offset.total_seconds()*1000)
        try:
            # Validate gap/overlap in the mapped year, not the extended epoch.
            utc=(local-offset).replace(tzinfo=timezone.utc)
            valid=utc.astimezone(zone).replace(tzinfo=None)==local
        except (OverflowError,ValueError):
            # The UTC side can fall just outside years 1..9999. IANA's
            # pre-transition/final rules agree for both folds at those edges.
            valid=local.replace(tzinfo=zone,fold=0).utcoffset()==local.replace(tzinfo=zone,fold=1).utcoffset()
        if abs(epoch)>8640000000000000:raise CalendarRangeError('date/time value is outside of supported range')
        if valid:candidates.append(epoch)
    return min(candidates) if candidates else None


parseLocalCalendar=parse_local_calendar
parseOffsetInstant=parse_offset_instant
fourDigitYearEpoch=four_digit_year_epoch
isFourDigitYearInstant=is_four_digit_year_instant
formatFourDigitYearInstant=format_four_digit_year_instant
canonicalizeTimeZone=canonicalize_time_zone
resolveLocalInstant=resolve_local_instant
