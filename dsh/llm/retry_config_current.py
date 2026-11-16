"""Current provider-owned retry configuration; detached from mutable settings."""
import copy
import math

from dsh.llm.retry_policy import MAX_TIMER_DELAY_MS, DEFAULT_CODES, RetryPolicyError

ABSENT = object()


def _fail(message):
    raise RetryPolicyError(message)


def _keys(config, allowed, path):
    for key in config:
        if key not in allowed: _fail(path+': unknown key "'+str(key)+'"')


def resolveRetryPolicy(config=ABSENT, path='retryPolicy'):
    if config is ABSENT: config = dict(mode='normal')
    if config is None: raise TypeError("Cannot read properties of null (reading 'mode')")
    mode = config.get('mode')
    if mode not in ('normal','always'): _fail(path+'.mode must be "normal" or "always"')
    _keys(config, ('mode','maxRetries','retryableCodes','backoff'), path)
    result = dict(mode=mode)
    if mode == 'normal':
        retries = config.get('maxRetries')
        retries = 5 if retries is None else retries
        if type(retries) not in (int,float) or not 0 <= retries <= 9007199254740991 or int(retries) != retries:
            _fail(path+'.maxRetries must be a non-negative safe integer')
        codes = config.get('retryableCodes')
        codes = DEFAULT_CODES if codes is None else codes
        if len(codes) == 0: _fail(path+'.retryableCodes must not be empty')
        if any(not isinstance(code,str) or not code for code in codes): _fail(path+'.retryableCodes must contain only non-empty strings')
        if len(set(codes)) != len(codes): _fail(path+'.retryableCodes must not contain duplicates')
        result.update(maxRetries=retries,retryableCodes=list(codes))
    backoff = config.get('backoff', ABSENT)
    if backoff is None: raise TypeError('Cannot convert undefined or null to object')
    if backoff is ABSENT: backoff = {}
    _keys(backoff,('initialDelayMs','maxDelayMs','jitterRatio'),path+'.backoff')
    for key, default in [('initialDelayMs',500),('maxDelayMs',10000),('jitterRatio',.1)]:
        value = backoff.get(key)
        result[key] = default if value is None else value
    for key in ('initialDelayMs','maxDelayMs'):
        value = result[key]
        if type(value) not in (int,float) or not 0 < value <= MAX_TIMER_DELAY_MS or not math.isfinite(value):
            _fail(path+'.backoff.'+key+' must be a positive finite number no greater than '+str(MAX_TIMER_DELAY_MS))
    if result['initialDelayMs'] > result['maxDelayMs']:
        _fail(path+'.backoff.initialDelayMs must be less than or equal to maxDelayMs')
    value = result['jitterRatio']
    if type(value) not in (int,float) or not 0 <= value <= 1 or not math.isfinite(value):
        _fail(path+'.backoff.jitterRatio must be between 0 and 1')
    return copy.deepcopy(result)
