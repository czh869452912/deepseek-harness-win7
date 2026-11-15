"""Protocol-aware inbound authority fence for the candidate Connection."""
from dsh.host.connection.api_trust import is_loopback_hostname
from dsh.host.connection.browser_auth import header
from dsh.host.http_proxy_policy import parse_url


def authority(value, protocol='http:'):
    return parse_url(protocol + '//' + value) if isinstance(value, str) else None


def is_remote_authority(entry):
    parsed = authority(entry)
    return parsed is None or not is_loopback_hostname(parsed['hostname'])


def is_trusted_api_request(request, trusted_hosts, bind_host=None, protocol='http:'):
    headers = request.get('headers', {})
    host = header(headers, 'host')
    parsed = authority(host, protocol)
    if parsed is None:
        return False
    trusted = is_loopback_hostname(parsed['hostname'])
    for entry in trusted_hosts:
        configured = authority(entry, protocol)
        if configured is None:
            continue
        # Parsing both schemes distinguishes an explicit default port from no port.
        other = authority(entry, 'https:' if protocol == 'http:' else 'http:')
        portless = other is not None and configured['port'] != other['port']
        if configured['hostname'] == parsed['hostname'] and (portless or configured['port'] == parsed['port']):
            trusted = True
    if bind_host is not None:
        address = bind_host.split('%', 1)[0]
        bound = authority('[' + address + ']' if ':' in address else address)
        if bound is not None and bound['hostname'] == parsed['hostname']:
            trusted = True
    if not trusted or header(headers, 'sec-fetch-site') == 'cross-site':
        return False
    origin = header(headers, 'origin')
    if origin is None:
        return True
    source = parse_url(origin)
    if source is None or source['protocol'] not in ('http:', 'https:'):
        return False
    target = authority(host, source['protocol'])
    return target is not None and source['hostname'] == target['hostname'] and source['port'] == target['port']
