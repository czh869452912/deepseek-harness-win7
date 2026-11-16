"""Credential-free Messages protocol settings for the split DeepSeek providers."""
import copy
import json
import math
from pathlib import Path
import re
from urllib.parse import urlsplit

from dsh.host.http_proxy_policy import parse_url
from dsh.llm.deepseek_config import DeepSeekConfigError
from dsh.llm.model_listing import InvalidListingURL
from dsh.llm.retry_config_current import ABSENT, resolveRetryPolicy
from dsh.settings.provider import deep_equal_json
from dsh.typert.stores import field

_DEFAULTS = json.loads((Path(__file__).resolve().parents[1]/'resources/deepseek_defaults_022.json').read_text(encoding='utf-8'))
PUBLIC_BASE_URL = _DEFAULTS['baseURL']


def _fail(message):
    raise DeepSeekConfigError('llm-deepseek: '+message)


def _integer(value, safe=False, minimum=1):
    return type(value) in (int,float) and minimum <= value <= 1.7976931348623157e308 and (not safe or value <= 9007199254740991) and math.isfinite(value) and int(value) == value


def resolveModels(models=None):
    models = _DEFAULTS['models'] if models is None else models
    resolved, seen = [], set()
    for model in models:
        if 'imageDetail' in model: _fail('catalog model imageDetail is no longer supported; use imagePixelBudget')
        model_id = model['id']
        if not model_id: _fail('catalog model ids must be non-empty')
        prefix = 'catalog model "'+model_id+'" '
        if 'name' in model and model['name'] == '': _fail(prefix+'has an empty name')
        for key in ('contextWindow','maxTokens'):
            if key in model and not _integer(model[key]): _fail(prefix+key+' must be a positive integer')
        modalities = model.get('inputModalities')
        if modalities is None: modalities = ['text']
        if not modalities: _fail(prefix+'inputModalities must not be empty')
        if any(value not in ('text','image') for value in modalities):
            _fail(prefix+'inputModalities must contain only "text" and "image"')
        if len(set(modalities)) != len(modalities): _fail(prefix+'inputModalities must not contain duplicates')
        has_image = 'image' in modalities
        if not has_image and any(key in model for key in ('imagePixelBudget','imageMaxBytes')):
            _fail('text-only '+prefix+'cannot declare image request limits')
        if 'imagePixelBudget' in model and model['imagePixelBudget'] != 'low' and not _integer(model['imagePixelBudget'],True):
            _fail(prefix+'imagePixelBudget must be "low" or a positive safe integer')
        if 'imageMaxBytes' in model and not _integer(model['imageMaxBytes'],True): _fail(prefix+'imageMaxBytes must be a positive safe integer')
        if 'systemPromptUpdate' in model and model['systemPromptUpdate'] != 'in-history': _fail(prefix+'systemPromptUpdate must be "in-history" when present')
        if 'toolUpdate' in model and model['toolUpdate'] not in ('in-history','addition-only'):
            _fail(prefix+'toolUpdate must be "in-history" or "addition-only" when present')
        if model_id in seen: _fail('duplicate catalog model "'+model_id+'"')
        seen.add(model_id)
        result = {key:copy.deepcopy(model[key]) for key in ('id','name','description','contextWindow','maxTokens','systemPromptUpdate','toolUpdate') if key in model}
        result['inputModalities'] = list(modalities)
        if has_image:
            if 'imagePixelBudget' in model: result['imagePixelBudget'] = model['imagePixelBudget']
            result['imageMaxBytes'] = model.get('imageMaxBytes',_DEFAULTS['models'][0]['imageMaxBytes'])
        resolved.append(result)
    return resolved


def isBuiltInCatalog(models):
    return deep_equal_json(models,resolveModels())


def resolveAdapterOptions(config, environment=None):
    if 'protocol' in config: _fail('protocol is not configurable; remove it and use a Messages-compatible baseURL')
    if config.get('thinking') == 'disabled' and 'reasoningEffort' in config and config['reasoningEffort'] != 'off':
        _fail('only reasoningEffort "off" can be configured when thinking is disabled')
    for key, safe in [('defaultContextWindow',False),('maxTokens',True)]:
        if key in config and not _integer(config[key],safe): _fail(key+' must be a positive '+('safe ' if safe else '')+'integer')
    options = copy.deepcopy(_DEFAULTS)
    for key in ('streamIdleTimeoutMs','maxRequestFilesBytes','maxInlineRequestImageBytes','maxImagesPerRequest',
                'imageOffloadByteQuantum','inlineImageOffloadByteQuantum','imageOffloadCountQuantum','filesApiTimeoutMs'):
        value = config.get(key)
        value = options[key] if value is None else value
        if key in ('streamIdleTimeoutMs','filesApiTimeoutMs'):
            if type(value) not in (int,float) or not 0 < value <= 2147483647 or not math.isfinite(value):
                _fail(key+' must be a positive finite number no greater than 2147483647')
        elif not _integer(value,True): _fail(key+' must be a positive safe integer')
        options[key] = value
        limit = {'imageOffloadByteQuantum':'maxRequestFilesBytes','inlineImageOffloadByteQuantum':'maxInlineRequestImageBytes',
                 'imageOffloadCountQuantum':'maxImagesPerRequest'}.get(key)
        if limit and value > options[limit]: _fail(key+' must not exceed '+limit)
    for key, target in [('fileExpiresAfterSeconds','expiresAfterSeconds'),('fileRefreshMarginSeconds','refreshMarginSeconds'),('fileQuotaCleanupBatch','quotaCleanupBatch')]:
        value = config.get(key)
        options['filePolicy'][target] = options['filePolicy'][target] if value is None else value
    expires, margin, batch = (options['filePolicy'][key] for key in ('expiresAfterSeconds','refreshMarginSeconds','quotaCleanupBatch'))
    if not _integer(expires,True) or not 3600 <= expires <= 2592000: _fail('fileExpiresAfterSeconds must be an integer from 3600 through 2592000')
    if not _integer(margin,True,0) or margin >= expires: _fail('fileRefreshMarginSeconds must be a non-negative integer below fileExpiresAfterSeconds')
    if not _integer(batch,True) or not 1 <= batch <= 1000: _fail('fileQuotaCleanupBatch must be an integer from 1 through 1000')
    base = config.get('baseURL')
    if base is None and environment is not None:
        base = field(environment.get('DEEPSEEK_BASE_URL'),'value')
    base = PUBLIC_BASE_URL if base is None else base
    parsed = parse_url(base)
    if parsed is None: raise InvalidListingURL('Invalid URL')
    # Special-scheme URL parsing ignores ASCII tab/newline and normalizes slash.
    normalized = re.sub(r'[\t\r\n]','',base.strip(''.join(chr(value) for value in range(33))))
    match = re.match(r'^([A-Za-z][A-Za-z0-9+.-]*):',normalized)
    root = urlsplit(parsed['protocol']+'//'+normalized[match.end():].replace('\\','/').lstrip('/'))
    if parsed['protocol'] not in ('http:','https:') or root.username or root.password or root.query or root.fragment:
        _fail('Messages baseURL must be an HTTP(S) root without credentials, query, or fragment')
    options.update(baseURL=base,models=resolveModels(config.get('models')),defaults={key:copy.deepcopy(config[key]) for key in ('thinking','reasoningEffort') if key in config},
                   retryPolicy=resolveRetryPolicy(config.get('retryPolicy',ABSENT),'llm-deepseek: retryPolicy'))
    for key in ('maxTokens','defaultContextWindow'):
        if key in config: options[key] = config[key]
    return options
