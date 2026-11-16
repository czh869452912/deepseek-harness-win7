"""API-key and account route settings over the shared Messages protocol."""
import copy
import json
from pathlib import Path

from dsh.credentials.credentials import credential_ref
from dsh.llm.deepseek_config_current import PUBLIC_BASE_URL, resolveAdapterOptions, isBuiltInCatalog, plainOptions
from dsh.llm.model_listing import modelListingURL
from dsh.llm.model_listing_cache import resolveListingTiming
from dsh.cordis.schema import Schema
from dsh.cordis.utils import js_to_string


class RouteConfigError(ValueError):
    name = 'Error'


def routeSchema(kind):
    schemas = json.loads((Path(__file__).resolve().parents[1]/'resources/deepseek_route_schemas_022.json').read_text(encoding='utf-8'))
    return Schema.from_json(schemas[kind])


def resolveApiKeyOptions(config, environment=None):
    timing = resolveListingTiming(config,'llm-deepseek-api-key')
    messages = {key:value for key,value in config.items() if key not in ('modelsTimeoutMs','modelsMaxAgeMs','apiKeyEnv')}
    connection = resolveAdapterOptions(messages,environment)
    ref = config.get('apiKeyEnv') if config.get('apiKeyEnv') is not None else 'DEEPSEEK_API_KEY'
    # Source's branded helper tests the JS string coercion but returns the
    # original value; normal Loader configuration has already required string.
    credential_ref(js_to_string(ref))
    connection['apiKeyEnv'] = copy.deepcopy(ref)
    if modelListingURL(connection['baseURL']) == modelListingURL(PUBLIC_BASE_URL) and isBuiltInCatalog(connection['models']):
        connection['listing'] = dict(url=modelListingURL(connection['baseURL']),**timing)
    return connection


def _override(model_id, override):
    if not model_id: raise RouteConfigError('llm-deepseek-account: modelOverrides keys must be non-empty model ids')
    if 'id' in override: raise RouteConfigError('llm-deepseek-account: modelOverrides.'+model_id+' sets "id", which is its key')
    declared = {key:copy.deepcopy(value) for key,value in override.items() if not (isinstance(value,list) and len(value) == 0)}
    try:
        standin = dict(inputModalities=['text','image'])
        standin.update(declared);standin['id'] = model_id
        resolveAdapterOptions(dict(models=[standin]))
    except Exception as error:
        name = getattr(error,'name','TypeError' if isinstance(error,TypeError) else 'Error')
        raise RouteConfigError('llm-deepseek-account: modelOverrides.'+model_id+' is invalid: '+name+': '+str(error)) from error
    return declared


def resolveAccountOptions(options, environment=None):
    if 'models' in options:
        raise RouteConfigError('llm-deepseek-account: models is no longer configurable; the account /models listing supplies the catalog. '
            +'Remove models from this entry and adjust single models with modelOverrides.<model id>')
    timing = resolveListingTiming(options,'llm-deepseek-account')
    protocol = resolveAdapterOptions({key:value for key,value in options.items() if key not in ('modelsTimeoutMs','modelsMaxAgeMs','modelOverrides')},environment)
    overrides = options.get('modelOverrides',{})
    if overrides is None: raise TypeError('Cannot convert undefined or null to object')
    return dict(protocol=protocol,catalog=dict(url=modelListingURL(protocol['baseURL']),**timing),
                modelOverrides={model_id:_override(model_id,override) for model_id,override in overrides.items()})


plainAccountOptions = plainOptions
