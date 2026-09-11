"""Local TLS caching composed with upstream pool ownership, without agent startup."""
import ssl
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest

from agent import process_bootstrap as bootstrap


@pytest.fixture
def transport_scope(monkeypatch):
    for name in ('HTTPS_PROXY', 'HTTP_PROXY', 'ALL_PROXY', 'https_proxy',
                 'http_proxy', 'all_proxy', 'NO_PROXY', 'no_proxy'):
        monkeypatch.delenv(name, raising=False)
    bootstrap.close_shared_transports()
    monkeypatch.setattr(bootstrap, '_DEFAULT_SSL_CONTEXT', None)
    yield
    bootstrap.close_shared_transports()


def test_stock_context_cache_and_custom_verification_stay_separate(transport_scope):
    clients = []
    try:
        first = bootstrap.build_keepalive_http_client('https://example.invalid')
        second = bootstrap.build_keepalive_http_client('https://example.invalid')
        clients.extend((first, second))
        assert isinstance(first, httpx.Client) and isinstance(second, httpx.Client)
        assert first is not second
        assert first._transport._inner is second._transport._inner
        assert first._transport._pool._ssl_context is bootstrap._DEFAULT_SSL_CONTEXT
        assert bootstrap._DEFAULT_SSL_CONTEXT.verify_mode == ssl.CERT_REQUIRED
        assert bootstrap._DEFAULT_SSL_CONTEXT.check_hostname

        custom = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        custom_client = bootstrap.build_keepalive_http_client('https://example.invalid', verify=custom)
        insecure = bootstrap.build_keepalive_http_client('https://example.invalid', verify=False)
        clients.extend((custom_client, insecure))
        assert custom_client._transport._pool._ssl_context is custom
        assert custom_client._transport._inner is not first._transport._inner
        assert insecure._transport._pool._ssl_context.verify_mode == ssl.CERT_NONE
        assert first._transport._pool._ssl_context.verify_mode == ssl.CERT_REQUIRED
    finally:
        for client in clients:
            if client is not None:
                client.close()


def test_shared_pool_remains_usable_after_sibling_close(transport_scope):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'

        def do_GET(self):  # noqa: N802
            self.send_response(200)
            self.send_header('Content-Length', '2')
            self.end_headers()
            self.wfile.write(b'ok')

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f'http://127.0.0.1:{server.server_address[1]}'
    clients = []
    try:
        first = bootstrap.build_keepalive_http_client(url)
        second = bootstrap.build_keepalive_http_client(url)
        clients.extend((first, second))
        assert first.get(url).text == 'ok'
        first.close()
        assert second.get(url).text == 'ok'
        successor = bootstrap.build_keepalive_http_client(url)
        clients.append(successor)
        assert successor.get(url).text == 'ok'
        with pytest.raises(RuntimeError):
            first.get(url)
    finally:
        for client in clients:
            if client is not None:
                client.close()
        bootstrap.close_shared_transports()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
