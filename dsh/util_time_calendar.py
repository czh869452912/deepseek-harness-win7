"""Gregorian date walks independent of datetime's year 1..9999 limit."""
from datetime import timedelta

from dsh.util_time_instant import EPOCH,ZoneInfo,_calendar_days


def calendar_date(days):
    shifted=days+719468;era=shifted//146097;day_of_era=shifted-era*146097
    year_of_era=(day_of_era-day_of_era//1460+day_of_era//36524-day_of_era//146096)//365
    year=year_of_era+era*400
    day_of_year=day_of_era-(365*year_of_era+year_of_era//4-year_of_era//100)
    month_prime=(5*day_of_year+2)//153
    day=day_of_year-(153*month_prime+2)//5+1
    month=month_prime+(3 if month_prime<10 else -9)
    return year+(month<=2),month,day


def local_epoch(epoch,time_zone):
    utc=EPOCH+timedelta(milliseconds=epoch);zone=ZoneInfo(time_zone)
    try:offset=zone.fromutc(utc.replace(tzinfo=zone)).utcoffset()
    except (ValueError,OverflowError):
        # Boundary projection may cross year zero/10000. The mapped calendar
        # has the same weekday/leap cycle and the same pre/final zone rules.
        year=utc.year+400 if utc.year==1 else utc.year-400
        offset=zone.fromutc(utc.replace(year=year,tzinfo=zone)).utcoffset()
    return epoch+int(offset.total_seconds()*1000)


def local_day(epoch,time_zone):return local_epoch(epoch,time_zone)//86400000


def day_parts(day,time):
    year,month,date=calendar_date(day)
    clock,fraction=time.split('.')
    hour,minute,second=map(int,clock.split(':'))
    return dict(year=year,month=month,day=date,hour=hour,minute=minute,second=second,millisecond=int(fraction))


def iso_weekday(day):return (day+3)%7+1


calendar_days=_calendar_days
