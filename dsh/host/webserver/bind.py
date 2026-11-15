"""Concrete socket address contract of the rc022 WebServer."""
import ipaddress
import json
import re


def parse_ip_literal(host):
    if not isinstance(host, str):
        return None
    bare, separator, zone = host.partition('%')
    if separator and (':' not in bare or not re.fullmatch(r'[0-9A-Za-z.:-]+', zone)):
        return None
    # Python 3.8's IPv4 parser accepts leading zeros; node:net does not.
    tail = bare.rsplit(':', 1)[-1]
    if '.' in tail and any(len(part) > 1 and part.startswith('0') for part in tail.split('.')):
        return None
    try:
        address = ipaddress.ip_address(bare)
    except ValueError:
        return None
    return address.ipv4_mapped or address if address.version == 6 else address


def not_literal_error(host):
    return ValueError('webserver: host {} is not a concrete IPv4 or IPv6 address literal'.format(json.dumps(host, ensure_ascii=False)))


def validate_host(host):
    address = parse_ip_literal(host)
    if address is None:
        raise not_literal_error(host)
    if int(address) == 0:
        raise ValueError('webserver: host {} is an unspecified (wildcard) address, which is not supported: binding every interface would expose remote code execution to the network; bind one concrete IPv4 or IPv6 address of a local interface instead'.format(json.dumps(host, ensure_ascii=False)))
    return host


def is_wildcard_host(host):
    address = parse_ip_literal(host)
    return address is not None and int(address) == 0


def is_loopback_host(host):
    address = parse_ip_literal(host)
    return address is not None and address.is_loopback


def normalize_bind_address(host):
    address = parse_ip_literal(host)
    if address is None:
        raise not_literal_error(host)
    return str(address)


def bind_url_host(host):
    bare, separator, zone = host.partition('%')
    loopback = is_loopback_host(bare)
    if separator and not loopback:
        return None
    text = normalize_bind_address(bare) if loopback else host
    address = parse_ip_literal(text)
    # net.isIP validates the complete text before adding brackets; invalid
    # callers still receive their original text from this presentation helper.
    ipv6 = address is not None and ':' in text
    return '[' + text + ']' if ipv6 else text
