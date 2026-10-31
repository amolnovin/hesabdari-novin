# -*- coding: utf-8 -*-
"""گیرندهٔ سبک webhook ووکامرس با امضای HMAC SHA-256."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

import db

MAX_BODY = 2 * 1024 * 1024
TOPICS = {
    "order.created",
    "order.updated",
    "order.deleted",
    "product.created",
    "product.updated",
    "product.deleted",
    "customer.created",
    "customer.updated",
    "customer.deleted",
}


def signature(raw: bytes, secret: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), raw, hashlib.sha256).digest()
    return base64.b64encode(digest).decode("ascii")


def verify(raw: bytes, provided: str, secret: str) -> bool:
    return bool(provided and secret) and hmac.compare_digest(
        signature(raw, secret), provided.strip()
    )


class WooWebhookServer:
    def __init__(self, host="127.0.0.1", port=8765):
        self.host, self.port = host, int(port)
        self.server = None
        self.thread = None

    def start(self):
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                return

            def _reply(self, code, body):
                raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_POST(self):
                path = urlparse(self.path).path
                if path != "/woo/webhook":
                    return self._reply(404, {"error": "not_found"})
                try:
                    n = int(self.headers.get("Content-Length", "0"))
                except ValueError:
                    return self._reply(400, {"error": "bad_length"})
                if n <= 0 or n > MAX_BODY:
                    return self._reply(413, {"error": "payload_too_large"})
                raw = self.rfile.read(n)
                # Settings DB handle is opened/closed per request to avoid sharing across threads.
                c = db.connect()
                try:
                    secret = db.get_setting(c, "woo_webhook_secret", "")
                    enabled = db.get_setting(c, "woo_webhook_enabled", "0") == "1"
                    if not enabled:
                        return self._reply(503, {"error": "webhook_disabled"})
                    topic = self.headers.get("X-WC-Webhook-Topic", "")
                    if topic not in TOPICS or not verify(
                        raw, self.headers.get("X-WC-Webhook-Signature", ""), secret
                    ):
                        return self._reply(401, {"error": "invalid_signature_or_topic"})
                    try:
                        data = json.loads(raw)
                        remote_id = int(data.get("id") or 0)
                        if remote_id <= 0:
                            raise ValueError("missing id")
                    except Exception:
                        return self._reply(400, {"error": "invalid_payload"})
                    with db.tx(c):
                        c.execute(
                            "INSERT INTO woo_events(topic,remote_id,payload) VALUES (?,?,?)",
                            (topic, remote_id, json.dumps(data, ensure_ascii=False)),
                        )
                    return self._reply(202, {"accepted": True})
                finally:
                    c.close()

        self.server = ThreadingHTTPServer((self.host, self.port), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(
            target=self.server.serve_forever, name="WooWebhookHTTP", daemon=True
        )
        self.thread.start()
        return self

    def stop(self):
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            self.server = None
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=3)
