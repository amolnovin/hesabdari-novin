# -*- coding: utf-8 -*-
"""کلاینت REST ووکامرس (wc/v3) بدون وابستگی خارجی.

احراز هویت: Basic Auth با consumer_key/consumer_secret روی HTTPS.
برخی هاست‌ها هدر Authorization را حذف می‌کنند؛ در آن حالت query_auth=True.
"""

from __future__ import annotations

import base64
import json
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


class WooError(Exception):
    def __init__(self, message: str, status: int = 0, code: str = ""):
        super().__init__(message)
        self.status = status
        self.code = code


class WooClient:
    def __init__(
        self,
        url: str,
        consumer_key: str,
        consumer_secret: str,
        *,
        timeout: int = 25,
        query_auth: bool = False,
        verify_ssl: bool = True,
        version: str = "wc/v3",
        retries: int = 2,
    ):
        self.url = (url or "").rstrip("/")
        if not self.url:
            raise WooError("آدرس فروشگاه ووکامرس وارد نشده است")
        if not self.url.startswith(("https://", "http://")):
            self.url = "https://" + self.url
        self.consumer_key = consumer_key or ""
        self.consumer_secret = consumer_secret or ""
        self.timeout = timeout
        self.query_auth = query_auth
        self.version = version
        self.retries = retries
        self.ctx = ssl.create_default_context()
        if not verify_ssl:
            self.ctx.check_hostname = False
            self.ctx.verify_mode = ssl.CERT_NONE

    def _request(
        self,
        method: str,
        path: str,
        params: dict | None = None,
        body: dict | None = None,
    ) -> tuple[Any, dict]:
        params = dict(params or {})
        if self.query_auth:
            params["consumer_key"] = self.consumer_key
            params["consumer_secret"] = self.consumer_secret
        query = urllib.parse.urlencode(params, doseq=True)
        api = f"{self.url}/wp-json/{self.version}/{path.lstrip('/')}"
        if query:
            api += ("&" if "?" in api else "?") + query
        data = (
            json.dumps(body, ensure_ascii=False).encode("utf-8")
            if body is not None
            else None
        )
        headers = {"Accept": "application/json", "User-Agent": "HesabdariNovin/3.0"}
        if data is not None:
            headers["Content-Type"] = "application/json; charset=utf-8"
        if not self.query_auth:
            token = base64.b64encode(
                f"{self.consumer_key}:{self.consumer_secret}".encode()
            ).decode()
            headers["Authorization"] = f"Basic {token}"
        last_err: Exception | None = None
        for attempt in range(self.retries + 1):
            req = urllib.request.Request(
                api, data=data, headers=headers, method=method.upper()
            )
            try:
                with urllib.request.urlopen(
                    req, timeout=self.timeout, context=self.ctx
                ) as resp:
                    raw = resp.read().decode("utf-8")
                    payload = json.loads(raw) if raw else None
                    return payload, dict(resp.headers)
            except urllib.error.HTTPError as e:
                raw = e.read().decode("utf-8", "replace")
                try:
                    err = json.loads(raw)
                    msg = err.get("message") or raw
                    code = err.get("code") or ""
                except Exception:
                    msg, code = raw, ""
                if e.code in (429, 500, 502, 503, 504) and attempt < self.retries:
                    time.sleep(1.5 * (attempt + 1))
                    last_err = WooError(msg, e.code, code)
                    continue
                raise WooError(f"خطای ووکامرس {e.code}: {msg}", e.code, code) from e
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                last_err = e
                if attempt < self.retries:
                    time.sleep(1.0 * (attempt + 1))
                    continue
                raise WooError(f"اتصال به فروشگاه ناموفق بود: {e}") from e
        raise WooError(str(last_err or "خطای نامشخص"))

    def get(self, path: str, **params):
        return self._request("GET", path, params)[0]

    def post(self, path: str, body: dict):
        return self._request("POST", path, body=body)[0]

    def put(self, path: str, body: dict):
        return self._request("PUT", path, body=body)[0]

    def delete(self, path: str, **params):
        return self._request("DELETE", path, params)[0]

    def list_all(
        self, path: str, *, per_page: int = 100, max_pages: int = 200, **params
    ):
        page = 1
        out = []
        while page <= max_pages:
            data, headers = self._request(
                "GET", path, {**params, "per_page": per_page, "page": page}
            )
            if not isinstance(data, list):
                break
            out.extend(data)
            total_pages = int(
                headers.get("X-WP-TotalPages") or headers.get("x-wp-totalpages") or 1
            )
            if page >= total_pages or not data:
                break
            page += 1
        return out

    def test_connection(self) -> dict:
        data = self.get("products", per_page=1)
        return {
            "ok": True,
            "products_sample": len(data) if isinstance(data, list) else 0,
        }
