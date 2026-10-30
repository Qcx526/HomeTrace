"""Rejected requests deliver errors even when a small POST body arrives later.

Loopback transport tests; no private data, model requests, or business operations.
"""
from email.message import Message
import http.client
import socket
import threading
import time
from types import SimpleNamespace

import pytest

from hometrace.demo_server import make_server


@pytest.fixture
def server():
    calls = []

    def forbidden(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError('Rejected request must not execute a business operation')

    value = make_server(SimpleNamespace(run=forbidden), 0)
    thread = threading.Thread(target=value.serve_forever, daemon=True)
    thread.start()
    try:
        yield value
    finally:
        value.shutdown()
        value.server_close()
        thread.join(timeout=5)
        assert not calls


@pytest.mark.parametrize('case,status', [
    ('host', 403), ('origin', 403), ('content-type', 415), ('unknown-path', 404),
])
def test_error_response_survives_delayed_post_body(server, case, status):
    body = b'{"scenario":"moved","strategy":"memory_first"}'
    host = 'evil.example' if case == 'host' else f'127.0.0.1:{server.server_port}'
    origin = 'Origin: https://evil.example\r\n' if case == 'origin' else ''
    content_type = 'text/plain' if case == 'content-type' else 'application/json'
    path = '/unknown-path' if case == 'unknown-path' else '/api/run'
    headers = (f'POST {path} HTTP/1.1\r\nHost: {host}\r\n{origin}'
               f'Content-Type: {content_type}\r\nContent-Length: {len(body)}\r\n\r\n')
    with socket.create_connection(('127.0.0.1', server.server_port), timeout=3) as connection:
        connection.sendall(headers.encode('ascii'))
        # The old server closes before this body and Windows loses the response.
        time.sleep(0.05)
        connection.sendall(body)
        response = http.client.HTTPResponse(connection)
        response.begin()
        assert response.status == status
        assert b'error' in response.read()


def test_missing_body_has_a_total_deadline(server):
    with socket.create_connection(('127.0.0.1', server.server_port), timeout=3) as connection:
        started = time.monotonic()
        connection.sendall((f'POST /api/run HTTP/1.1\r\nHost: 127.0.0.1:{server.server_port}\r\n'
                            'Content-Type: text/plain\r\nContent-Length: 5\r\n\r\n').encode('ascii'))
        response = http.client.HTTPResponse(connection)
        response.begin()
        assert response.status == 415
        assert b'Use application/json' in response.read()
        assert 0.8 <= time.monotonic() - started < 3


@pytest.mark.parametrize('headers', [
    [], [('Content-Length', '0')], [('Content-Length', '-1')],
    [('Content-Length', 'abc')], [('Content-Length', '65537')],
    [('Content-Length', '99999999999999999999999999999999999')],
    [('Content-Length', '5'), ('Content-Length', '5')],
    [('Content-Length', '5, 5')],
    [('Content-Length', '5'), ('Transfer-Encoding', 'chunked')],
])
def test_ambiguous_or_unbounded_framing_is_not_read(headers):
    with make_server(None, 0) as value:
        handler = object.__new__(value.RequestHandlerClass)
    handler.command, handler.close_connection = 'POST', False
    handler.headers = Message()
    for key, value in headers:
        handler.headers[key] = value
    # No rfile/connection at all: touching either would fail the test.
    replies = []
    handler._json = lambda payload, status: replies.append((payload, status))
    handler._reject({'error': 'invalid request'}, 415)
    assert replies == [({'error': 'invalid request'}, 415)]
    assert handler.close_connection


def test_trickling_body_cannot_reset_deadline_and_timeout_is_restored(monkeypatch):
    with make_server(None, 0) as value:
        handler = object.__new__(value.RequestHandlerClass)
    handler.command = 'POST'
    handler.headers = Message()
    handler.headers['Content-Length'] = '100'
    elapsed, reads, timeouts, replies = [0.0], [], [], []

    def read_one(size):
        reads.append(size)
        elapsed[0] += 0.4
        return b'x'

    monkeypatch.setattr('hometrace.demo_server.time.monotonic', lambda: elapsed[0])
    handler.connection = SimpleNamespace(gettimeout=lambda: 7.0, settimeout=timeouts.append)
    handler.rfile = SimpleNamespace(read1=read_one)
    handler._json = lambda payload, status: replies.append(status)
    handler._reject({'error': 'invalid request'}, 415)
    assert len(reads) == 3  # Progress never extends the total deadline.
    assert timeouts == pytest.approx([1.0, 0.6, 0.2, 7.0])
    assert replies == [415]
