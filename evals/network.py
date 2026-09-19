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
