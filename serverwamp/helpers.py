import re
import socket

sub_first_cap = re.compile('(.)([A-Z][a-z]+)').sub
sub_all_caps = re.compile('([a-z0-9])([A-Z])').sub


def camel_to_snake(name):
    # Based on https://stackoverflow.com/a/1176023/1843865
    s1 = sub_first_cap(r'\1_\2', name)
    return sub_all_caps(r'\1_\2', s1).lower()


def format_sockaddr(net_family, sockaddr) -> str:
    if net_family == socket.AF_INET:
        return f'{sockaddr[0]}:{sockaddr[1]}'
    if net_family == socket.AF_INET6:
        return f'[{sockaddr[0]}]:{sockaddr[1]}'
    return str(sockaddr)
