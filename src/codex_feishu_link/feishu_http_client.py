from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping
import json
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


class FeishuApiError(RuntimeError):
    pass


@dataclass(slots=True)
class _TokenCache:
    access_token: str = ""
    expires_at: float = 0.0


class FeishuHttpClient:
    """Small stdlib-only client for Feishu token retrieval and message send."""

    def __init__(
        self,
        app_id: str,
        app_secret: str,
        *,
        base_url: str = "https://open.feishu.cn",
        receive_id_type: str = "chat_id",
        request_opener: Callable[..., Any] = urlopen,
        clock: Callable[[], float] = time.monotonic,
        timeout_seconds: float = 10.0,
        token_refresh_margin_seconds: float = 60.0,
    ) -> None:
        self.app_id = app_id.strip()
        self.app_secret = app_secret.strip()
        self.base_url = base_url.rstrip("/") or "https://open.feishu.cn"
        self.receive_id_type = receive_id_type.strip() or "chat_id"
        self.request_opener = request_opener
        self.clock = clock
        self.timeout_seconds = timeout_seconds
        self.token_refresh_margin_seconds = max(0.0, float(token_refresh_margin_seconds))
        self._token_cache = _TokenCache()

    def get_tenant_access_token(self, *, force_refresh: bool = False) -> str:
        now = self.clock()
        if (
            not force_refresh
            and self._token_cache.access_token
            and now < self._token_cache.expires_at
        ):
            return self._token_cache.access_token

        response = self._request_json(
            "POST",
            "/open-apis/auth/v3/tenant_access_token/internal",
            {
                "app_id": self.app_id,
                "app_secret": self.app_secret,
            },
            auth=False,
        )
        token = response.get("tenant_access_token")
        if not isinstance(token, str) or not token.strip():
            raise FeishuApiError("Feishu token response did not include tenant_access_token")

        expire_seconds = response.get("expire")
        if not isinstance(expire_seconds, (int, float)):
            expire_seconds = response.get("expire_in")
        if not isinstance(expire_seconds, (int, float)):
            expire_seconds = response.get("expires_in")
        if not isinstance(expire_seconds, (int, float)):
            expire_seconds = 7200

        self._token_cache.access_token = token.strip()
        self._token_cache.expires_at = now + max(
            0.0, float(expire_seconds) - self.token_refresh_margin_seconds
        )
        return self._token_cache.access_token

    def clear_token_cache(self) -> None:
        self._token_cache = _TokenCache()

    def send(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        body = dict(payload)
        receive_id = body.pop("receive_id", None)
        if not isinstance(receive_id, str) or not receive_id.strip():
            raise FeishuApiError("Message payload must include receive_id")
        receive_id_type = str(body.pop("receive_id_type", self.receive_id_type) or self.receive_id_type)
        return self._request_json(
            "POST",
            f"/open-apis/im/v1/messages?receive_id_type={quote(receive_id_type)}",
            {
                "receive_id": receive_id.strip(),
                **body,
            },
            auth=True,
        )

    def send_text_message(
        self,
        receive_id: str,
        text: str,
        *,
        receive_id_type: str | None = None,
    ) -> dict[str, Any]:
        return self.send(
            {
                "receive_id": receive_id,
                "receive_id_type": receive_id_type or self.receive_id_type,
                "msg_type": "text",
                "content": json.dumps({"text": text}, ensure_ascii=False),
            }
        )

    def _request_json(
        self,
        method: str,
        path: str,
        payload: Mapping[str, Any] | None = None,
        *,
        auth: bool,
    ) -> dict[str, Any]:
        headers = {
            "Content-Type": "application/json; charset=utf-8",
        }
        if auth:
            headers["Authorization"] = f"Bearer {self.get_tenant_access_token()}"

        body = None
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = Request(
            self._build_url(path),
            data=body,
            headers=headers,
            method=method,
        )
        try:
            with self.request_opener(request, timeout=self.timeout_seconds) as response:
                return self._decode_response(response)
        except HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace") if hasattr(exc, "read") else ""
            raise FeishuApiError(
                f"Feishu request failed: HTTP {exc.code} {exc.reason}: {error_body}"
            ) from exc
        except URLError as exc:
            raise FeishuApiError(f"Feishu request failed: {exc.reason}") from exc

    def _build_url(self, path: str) -> str:
        if path.startswith("http://") or path.startswith("https://"):
            return path
        if not path.startswith("/"):
            path = f"/{path}"
        return f"{self.base_url}{path}"

    def _decode_response(self, response: Any) -> dict[str, Any]:
        raw = response.read()
        if isinstance(raw, bytes):
            text = raw.decode("utf-8", errors="replace")
        else:
            text = str(raw)
        if not text.strip():
            return {}
        payload = json.loads(text)
        if not isinstance(payload, dict):
            raise FeishuApiError("Feishu response payload must be a JSON object")
        code = payload.get("code")
        if code not in (None, 0, "0"):
            message = payload.get("msg") or payload.get("message") or "unknown error"
            raise FeishuApiError(f"Feishu API returned code {code}: {message}")
        return payload
