"""Verify HTTPS against native OS trust, while honoring explicit CA overrides."""

from __future__ import annotations

import os
import ssl

import truststore


def ssl_context() -> ssl.SSLContext:
    cafile = os.environ.get("SSL_CERT_FILE")
    capath = os.environ.get("SSL_CERT_DIR")
    if cafile or capath:
        # An explicit private CA policy must not silently broaden to OS roots.
        try:
            return ssl.create_default_context(cafile=cafile, capath=capath)
        except OSError as exc:
            raise RuntimeError(
                "지정한 CA를 읽지 못했습니다. SSL_CERT_FILE/SSL_CERT_DIR 설정을 확인하세요."
            ) from exc
    return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
