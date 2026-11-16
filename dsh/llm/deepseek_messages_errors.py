"""HTTP and in-band Messages errors with provider-neutral serializable facts."""
import datetime
import math
import re
import time

from dsh.cordis.utils import _v8_parse_date_string,_local_utc_offset_seconds
from dsh.llm.llm_service import LlmError
from dsh.llm.provider_errors import is_context_window_exceeded,is_quota_exceeded


def providerErrorDetail(raw):
    error = raw.get('error') if isinstance(raw,dict) else None
    if not isinstance(error,dict): return ''
    return ' '.join(error[key] for key in ('code','type','message') if isinstance(error.get(key),str))


def _date_ms(value):
    parsed = _v8_parse_date_string(value)
    if parsed is None: return float('nan')
    year,month,day,hour,minute,second,ms,offset = parsed
    if offset is None:
        try: return datetime.datetime(year,month,day,hour,minute,second,ms*1000).timestamp()*1000
        except (ValueError,OverflowError,OSError): offset = _local_utc_offset_seconds()
    adjusted = year-(month <= 2)
    era = adjusted//400;yoe = adjusted-era*400
    doy = (153*(month+(-3 if month > 2 else 9))+2)//5+day-1
    days = era*146097+yoe*365+yoe//4-yoe//100+doy-719468
    result = ((days*24+hour)*3600+minute*60+second-offset)*1000+ms
    return result if abs(result) <= 8640000000000000 else float('nan')


def providerError(raw, status=None, headers=None):
    envelope = raw if isinstance(raw,dict) else {}
    error = envelope.get('error')
    error = error if isinstance(error,dict) else {}
    message = error.get('message')
    if not isinstance(message,str): message = 'DeepSeek Messages request failed ('+('stream error' if status is None else str(status))+')'
    kind = error.get('type') if isinstance(error.get('type'),str) else ''
    detail = kind+' '+(error['code'] if isinstance(error.get('code'),str) else '')+' '+message
    if status in (401,403) or kind in ('authentication_error','permission_error'): code = 'AUTH'
    elif is_quota_exceeded(detail) or status == 402: code = 'QUOTA'
    elif status == 429 or kind == 'rate_limit_error': code = 'RATE_LIMIT'
    elif is_context_window_exceeded(detail): code = 'CONTEXT_WINDOW_EXCEEDED'
    elif status in (400,413) or kind == 'invalid_request_error': code = 'INVALID_REQUEST'
    elif status is not None and status >= 500 or kind in ('api_error','overloaded_error'): code = 'SERVER'
    else: code = 'SERVER' if status is None else 'HTTP_'+str(status)
    normalized = {}
    for key,value in (headers or {}).items():
        key,value = key.lower(),value.strip(' \t\r\n')
        normalized[key] = normalized[key]+', '+value if key in normalized else value
    retry = normalized.get('retry-after')
    delay = float('nan')
    if retry is not None:
        delay = float(retry)*1000 if re.fullmatch(r'[0-9]+(?:\.[0-9]+)?',retry) else _date_ms(retry)-time.time()*1000
    request_id = next((normalized[key] for key in ('request-id','x-request-id','x-deepseek-request-id') if key in normalized),None)
    return LlmError(message,code,status=status,providerRetryAfterMs=delay if math.isfinite(delay) and delay > 0 else None,requestId=request_id or None)
