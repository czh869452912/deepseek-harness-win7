"""Bound-interface LAN snapshot using Win7 IP Helper or POSIX getifaddrs."""
import ctypes
import os
import socket


def ipv4_interfaces():
    if os.name == 'nt':
        from ctypes import wintypes
        class Address(ctypes.Structure):
            _fields_ = [('pointer', ctypes.c_void_p), ('length', ctypes.c_int)]
        class Unicast(ctypes.Structure):
            pass
        Unicast._fields_ = [('alignment', ctypes.c_ulonglong), ('next', ctypes.POINTER(Unicast)), ('address', Address)]
        class Adapter(ctypes.Structure):
            pass
        Adapter._fields_ = [('alignment', ctypes.c_ulonglong), ('next', ctypes.POINTER(Adapter)),
                           ('name', ctypes.c_char_p), ('unicast', ctypes.POINTER(Unicast))]
        query = ctypes.WinDLL('iphlpapi', use_last_error=True).GetAdaptersAddresses
        query.argtypes = [wintypes.ULONG, wintypes.ULONG, ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(wintypes.ULONG)]
        query.restype = wintypes.ULONG
        size = wintypes.ULONG(15 * 1024)
        for _ in range(3):
            buffer = ctypes.create_string_buffer(size.value)
            result = query(socket.AF_INET, 0x10, None, buffer, ctypes.byref(size))
            if result == 111:  # ERROR_BUFFER_OVERFLOW: adapter set changed.
                continue
            if result == 232:  # ERROR_NO_DATA
                return []
            if result:
                raise ctypes.WinError(result)
            addresses = []
            adapter = ctypes.cast(buffer, ctypes.POINTER(Adapter))
            while adapter:
                node = adapter.contents.unicast
                while node:
                    address = node.contents.address
                    if address.pointer and address.length >= 8:
                        raw = ctypes.string_at(address.pointer, 8)
                        if int.from_bytes(raw[:2], 'little') == socket.AF_INET:
                            addresses.append(socket.inet_ntoa(raw[4:8]))
                    node = node.contents.next
                adapter = adapter.contents.next
            return [address for address in addresses if not address.startswith('127.')]
        raise OSError('network interfaces kept changing during LAN trust snapshot')
    class IfAddrs(ctypes.Structure):
        pass
    IfAddrs._fields_ = [('next', ctypes.POINTER(IfAddrs)), ('name', ctypes.c_char_p),
                       ('flags', ctypes.c_uint), ('address', ctypes.c_void_p),
                       ('netmask', ctypes.c_void_p), ('destination', ctypes.c_void_p), ('data', ctypes.c_void_p)]
    libc = ctypes.CDLL(None, use_errno=True)
    head = ctypes.POINTER(IfAddrs)()
    libc.getifaddrs.argtypes = [ctypes.POINTER(ctypes.POINTER(IfAddrs))]
    libc.freeifaddrs.argtypes = [ctypes.POINTER(IfAddrs)]
    if libc.getifaddrs(ctypes.byref(head)):
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))
    addresses = []
    try:
        node = head
        while node:
            row = node.contents
            if row.address and not row.flags & 8:  # IFF_LOOPBACK
                raw = ctypes.string_at(row.address, 8)
                family = raw[1] if sys_platform_bsd() else int.from_bytes(raw[:2], 'little')
                if family == socket.AF_INET:
                    addresses.append(socket.inet_ntoa(raw[4:8]))
            node = row.next
    finally:
        libc.freeifaddrs(head)
    return addresses


def sys_platform_bsd():
    import sys
    return sys.platform == 'darwin' or 'bsd' in sys.platform


def resolve_lan_trust(bind_host, extra=()):
    addresses = ipv4_interfaces() if bind_host == '0.0.0.0' else []
    return {'lanAddresses': addresses, 'trustedHosts': addresses + list(extra)}
