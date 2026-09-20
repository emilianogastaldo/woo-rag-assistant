"""Blocco di rete condiviso da CLI offline e pytest, senza dipendenze extra."""

import socket
from contextlib import contextmanager
from unittest.mock import patch


def deny_network(*args, **kwargs):
    raise RuntimeError("network disabled in offline evaluation")


@contextmanager
def offline_network():
    with (
        patch.object(socket.socket, "connect", deny_network),
        patch.object(socket.socket, "connect_ex", deny_network),
        patch.object(socket, "create_connection", deny_network),
        patch.object(socket, "getaddrinfo", deny_network),
    ):
        yield


@contextmanager
def local_service_network(host, port):
    """Integration only: allow one resolved test service/port, deny all other sockets."""
    resolve = socket.getaddrinfo
    connect, connect_ex = socket.socket.connect, socket.socket.connect_ex
    addresses = {row[4][0] for row in resolve(host, port, type=socket.SOCK_STREAM)}

    def checked_resolve(name, target_port, *args, **kwargs):
        if name not in {host, *addresses} or int(target_port) != port:
            raise RuntimeError("network restricted to isolated test service")
        return resolve(name, target_port, *args, **kwargs)

    def checked_connect(sock, address, *, original=connect):
        if not isinstance(address, tuple) or address[0] not in addresses or address[1] != port:
            raise RuntimeError("network restricted to isolated test service")
        return original(sock, address)

    with (
        patch.object(socket, "getaddrinfo", checked_resolve),
        patch.object(socket.socket, "connect", checked_connect),
        patch.object(socket.socket, "connect_ex",
                     lambda sock, address: checked_connect(sock, address, original=connect_ex)),
    ):
        yield
