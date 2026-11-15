"""Protocol-bound browser and independent API operator cookie exchange."""
import hmac
import json
import time
import math
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from dsh.host.connection.browser_auth import (BrowserAuth, header, cookie_name,
    cookie_value, session_cookie, token_matches, encode_base64url,
    decode_base64url, signature, is_safe_integer)
from dsh.host.connection.trust_current import authority


def request_audience(headers, secure=False):
    parsed = authority(header(headers, 'host'), 'https:' if secure else 'http:')
    if parsed is None:
        return None
    host = parsed['hostname']
    if ':' in host:
        host = '[' + host + ']'
    if parsed['port'] != (443 if secure else 80):
        host += ':' + str(parsed['port'])
    return 'https://' + host if secure else host


def encode_cookie(payload, secret):
    body = encode_base64url(json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode('utf-8'))
    return 'v{}.{}.{}'.format(payload['version'], body, encode_base64url(signature(secret, body)))


def decode_cookie(value, secret):
    parts = value.split('.')
    if len(parts) != 3 or parts[0] not in ('v1', 'v2'):
        return None
    version, body, encoded = parts
    actual = decode_base64url(encoded)
    if actual is None or not hmac.compare_digest(actual, signature(secret, body)):
        return None
    try:
        raw = decode_base64url(body)
        decoded = json.loads(raw.decode('utf-8')) if raw is not None else None
    except (ValueError, UnicodeError):
        return None
    if not isinstance(decoded, dict) or type(decoded.get('version')) not in (int, float) or decoded['version'] not in (1, 2) or version != 'v' + str(int(decoded['version'])):
        return None
    def safe(value):
        return is_safe_integer(value) or type(value) is float and math.isfinite(value) and value.is_integer() and abs(value) <= 9007199254740991
    if not isinstance(decoded.get('authority'), str) or not all(safe(decoded.get(key)) for key in ('issuedAt', 'expiresAt')):
        return None
    result = {key: decoded[key] for key in ('version', 'authority', 'issuedAt', 'expiresAt')}
    if decoded['version'] == 2:
        if not isinstance(decoded.get('id'), str) or not decoded['id']:
            return None
        result['id'] = decoded['id']
    return result


def write_response(response, status, headers=None, body=None):
    response.write_status(status)
    for key, value in (headers or {}).items():
        response.write_header(key, value)
    if body is not None:
        response.write_body(body.encode('utf-8'))


class CurrentBrowserAuth(BrowserAuth):
    def authenticated_url(self, base_url):
        parsed = urlsplit(base_url)
        pairs = parse_qsl(parsed.query, keep_blank_values=True)
        result, replaced = [], False
        for key, value in pairs:
            if key == 'token':
                if not replaced:
                    result.append((key, self.launch_token))
                    replaced = True
            else:
                result.append((key, value))
        if not replaced:
            result.append(('token', self.launch_token))
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path or '/', urlencode(result), parsed.fragment))

    def authenticate(self, request, secure=False):
        audience = request_audience(request.get('headers'), secure)
        raw = header(request.get('headers'), 'cookie')
        if audience is None or raw is None:
            return None
        value = cookie_value(raw, cookie_name(audience))
        payload = decode_cookie(value, self.secret) if value is not None else None
        if payload is None or payload['authority'] != audience:
            return None
        now = int(time.time() * 1000)
        issued, expires = payload['issuedAt'], payload['expiresAt']
        if issued > now or expires <= now or expires <= issued or expires - issued > self.max_age_milliseconds:
            return None
        return payload

    def is_authenticated(self, request, secure=False):
        payload = self.authenticate(request, secure)
        return payload is not None and payload['version'] == 1

    def authenticate_api(self, request, secure=False):
        payload = self.authenticate(request, secure)
        return payload['id'] if payload is not None and payload['version'] == 2 else None

    def _cookie(self, audience, secure, version, peer_id=None):
        issued = int(time.time() * 1000)
        expires = issued + self.max_age_milliseconds
        payload = dict(version=version, authority=audience)
        if version == 2:
            payload['id'] = peer_id
        payload.update(issuedAt=issued, expiresAt=expires)
        value = session_cookie(cookie_name(audience), encode_cookie(payload, self.secret), expires, int(self.max_age_milliseconds / 1000))
        return value + '; Secure' if secure else value

    def authorize_index(self, request, response, secure=False):
        url = urlsplit(self._raw_url(request))
        tokens = [value for key, value in parse_qsl(url.query, keep_blank_values=True) if key == 'token']
        if tokens:
            audience = request_audience(request.get('headers'), secure)
            headers = {'cache-control': 'no-store', 'location': './', 'referrer-policy': 'no-referrer'}
            root_get = request.get('method') == 'GET' and (url.path or '/') == '/'
            if root_get and len(tokens) == 1 and audience is not None and token_matches(tokens[0], self.launch_token):
                headers['set-cookie'] = self._cookie(audience, secure, 1)
                write_response(response, 303, headers)
                return False
            if root_get and self.is_authenticated(request, secure):
                write_response(response, 303, headers)
                return False
            self.write_unauthorized(request, response)
            return False
        if self.is_authenticated(request, secure):
            return True
        self.write_unauthorized(request, response)
        return False

    def authorize_connect(self, request, response, secure, publish):
        url = urlsplit(self._raw_url(request))
        pairs = parse_qsl(url.query, keep_blank_values=True)
        declarations = [value for key, value in pairs if key == 'interactions']
        interactions = declarations[0] if declarations else 'none'
        if len(declarations) > 1 or interactions not in ('answer', 'none'):
            write_response(response, 400, {'cache-control': 'no-store', 'content-type': 'text/plain; charset=utf-8'}, 'interactions must be declared once as answer or none\n')
            return
        tokens = [value for key, value in pairs if key == 'token']
        audience = request_audience(request.get('headers'), secure)
        if request.get('method') != 'GET' or url.path != '/connect' or len(tokens) != 1 or audience is None or not token_matches(tokens[0], self.launch_token):
            self.write_unauthorized(request, response)
            return
        peer_id = publish(interactions)
        write_response(response, 302, {'cache-control': 'no-store', 'location': './api/remote.mux', 'referrer-policy': 'no-referrer', 'set-cookie': self._cookie(audience, secure, 2, peer_id)})

    authenticatedUrl = authenticated_url
    isAuthenticated = is_authenticated
    authenticateApi = authenticate_api
    authorizeIndex = authorize_index
    authorizeConnect = authorize_connect
