"""Platform client identity and deployment Cookie merging (rc.3 contract)."""
import re

from dsh.cordis.utils import js_to_string
from dsh.host.http_proxy_policy import JS_SPACE


def mergePlatformCookies(base, override):
    cookies = {}
    for header in (base, override):
        for pair in header.split(';'):
            separator = pair.find('=')
            if separator < 1:
                continue
            cookies[pair[:separator].strip(JS_SPACE)] = pair[separator+1:].strip(JS_SPACE)
    return '; '.join(name+'='+value for name, value in cookies.items())


def desktopClientHeaders(platform):
    if platform is None:
        return {}
    return {'x-client-platform': 'desktop-win' if platform == 'win32' else 'desktop-mac'}


def platformWireLocale(locale):
    return 'zh_CN' if re.split('[-_]', locale.lower())[0] == 'zh' else 'en_US'


def platformClientHeaders(platform, client):
    headers = {'x-client-bundle-id': '', 'x-client-platform': 'web'}
    headers.update(desktopClientHeaders(platform))
    headers.update({'x-client-version': client['version'],
                    'x-client-locale': platformWireLocale(client['locale']),
                    'x-client-timezone-offset': js_to_string(client['timezoneOffsetSeconds'])})
    return headers
