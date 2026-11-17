"""Consumer-independent failures and decision bounds for recurring rules."""
from dsh.util_time_instant import four_digit_year_epoch,is_four_digit_year_instant,CalendarRangeError


class RecurrenceInputError(ValueError):
    def __init__(self,reason,message,cause=None):
        self.reason=reason;self.cause=cause;super().__init__(message)


def parse_recurrence(parse):
    try:return dict(kind='accepted',rule=parse())
    except RecurrenceInputError as error:
        result=dict(kind='rejected',reason=error.reason,detail=str(error))
        if error.cause is not None:result['cause']=error.cause
        return result


def recurrence_decision(scheduled_at,accepted_at):
    saved=four_digit_year_epoch(scheduled_at)
    if not is_four_digit_year_instant(accepted_at) or saved['kind']=='rejected' or accepted_at<saved['epoch']:
        raise CalendarRangeError('Recurrence decision must be representable and at or after its committed target')
    return saved['epoch']
