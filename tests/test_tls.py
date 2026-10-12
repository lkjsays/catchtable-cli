import ipaddress
import os
import ssl
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from catchtable_cli.client import CatchTableClient
from catchtable_cli.config import CatchTableConfig
from catchtable_cli.tls import ssl_context


class TLSTests(unittest.TestCase):
    def test_native_context_keeps_verification_on(self):
        with patch.dict(os.environ, {}, clear=True):
            ctx = ssl_context()
        self.assertEqual(ctx.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(ctx.check_hostname)

    def test_invalid_explicit_ca_does_not_fallback(self):
        with patch.dict(
            os.environ,
            {"SSL_CERT_FILE": "/nonexistent-catchtable-test-ca.pem"},
            clear=True,
        ):
            with self.assertRaisesRegex(RuntimeError, "SSL_CERT_FILE"):
                ssl_context()

    def test_unknown_certificate_rejected_explicit_ca_accepted(self):
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
        now = datetime.now(timezone.utc)
        cert = (
            x509.CertificateBuilder()
            .subject_name(name)
            .issuer_name(name)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=1))
            .not_valid_after(now + timedelta(hours=1))
            .add_extension(
                x509.SubjectAlternativeName(
                    [x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]
                ),
                False,
            )
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), True)
            .sign(key, hashes.SHA256())
        )

        class Handler(BaseHTTPRequestHandler):
            def handle(self):
                try:
                    super().handle()
                except ConnectionResetError:
                    pass  # Expected when the client rejects our untrusted certificate.

            def do_GET(self):
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"ok")

            def log_message(self, *args):
                pass

        with tempfile.TemporaryDirectory() as directory:
            ca, private = Path(directory) / "ca.pem", Path(directory) / "key.pem"
            ca.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
            private.write_bytes(
                key.private_bytes(
                    serialization.Encoding.PEM,
                    serialization.PrivateFormat.PKCS8,
                    serialization.NoEncryption(),
                )
            )
            server = HTTPServer(("127.0.0.1", 0), Handler)
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(ca, private)
            server.socket = context.wrap_socket(server.socket, server_side=True)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                url = f"https://127.0.0.1:{server.server_port}"
                with patch.dict(os.environ, {}, clear=True):
                    with httpx.Client(verify=ssl_context(), trust_env=False) as client:
                        with self.assertRaises(httpx.ConnectError):
                            client.get(url)
                with patch.dict(os.environ, {"SSL_CERT_FILE": str(ca)}, clear=True):
                    with httpx.Client(verify=ssl_context(), trust_env=False) as client:
                        self.assertEqual(client.get(url).text, "ok")
            finally:
                server.shutdown()
                server.server_close()
                thread.join()


class RetryTests(unittest.IsolatedAsyncioTestCase):
    async def test_write_failure_is_not_replayed(self):
        client = CatchTableClient(
            CatchTableConfig(use_curl_cffi=False, use_keychain=False)
        )
        self.addAsyncCleanup(client.close)
        client._use_curl_cffi = True
        client._curl_client = AsyncMock()
        with patch.object(
            client, "_request_with_curl", side_effect=RuntimeError("ambiguous")
        ):
            with patch.object(client, "_should_fallback_to_httpx", return_value=True):
                with patch.object(
                    client, "_request_with_httpx", new_callable=AsyncMock
                ) as fallback:
                    with self.assertRaises(httpx.RequestError):
                        await client._request(
                            "POST", "/api/reservation/v2/dinings/create", json_body={}
                        )
                    fallback.assert_not_awaited()

    async def test_public_read_can_fallback(self):
        client = CatchTableClient(
            CatchTableConfig(use_curl_cffi=False, use_keychain=False)
        )
        self.addAsyncCleanup(client.close)
        client._use_curl_cffi = True
        client._curl_client = AsyncMock()
        with patch.object(
            client, "_request_with_curl", side_effect=RuntimeError("TLS")
        ):
            with patch.object(client, "_should_fallback_to_httpx", return_value=True):
                with patch.object(
                    client,
                    "_request_with_httpx",
                    new_callable=AsyncMock,
                    return_value={"data": {}},
                ) as fallback:
                    await client.autocomplete("test")
                    fallback.assert_awaited_once()
                    self.assertFalse(client._use_curl_cffi)
