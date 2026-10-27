"""Проверка самой оснастки: наружу фаззинг ходить не может."""
import socket

import pytest


def test_outbound_dns_and_connect_are_blocked(no_outbound):
    with pytest.raises(socket.gaierror):
        socket.getaddrinfo("api.vk.com", 443)
    s = socket.socket()
    try:
        with pytest.raises(OSError):
            s.connect(("93.184.216.34", 443))
    finally:
        s.close()
    assert len(no_outbound) == 2
    no_outbound.clear()   # попытки здесь — ожидаемые, не дефект оснастки


def test_limiter_is_off_here():
    from app.core.limiter import limiter

    assert limiter.enabled is False
