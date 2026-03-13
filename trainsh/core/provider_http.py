"""HTTP-backed provider operations."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional


class ExecutorProviderHttpMixin:
    def _coerce_http_headers(self, headers: Any) -> tuple[bool, str, Dict[str, str]]:
        if headers is None:
            return True, "", {}
        if not isinstance(headers, dict):
            return False, "Provider http headers must be an object", {}
        parsed: Dict[str, str] = {}
        for key, value in headers.items():
            if key is None:
                continue
            parsed[str(key)] = "" if value is None else str(value)
        return True, "", parsed

    def _coerce_http_statuses(self, value: Any) -> tuple[bool, str, List[int]]:
        if value is None:
            return True, "", [200]
        if isinstance(value, bool):
            return False, f"Invalid expected_status: {value!r}", []
        if isinstance(value, int):
            return True, "", [int(value)]
        if isinstance(value, (list, tuple, set)):
            parsed: List[int] = []
            for item in value:
                if isinstance(item, bool):
                    continue
                try:
                    parsed.append(int(item))
                except Exception:
                    return False, f"Invalid expected_status value: {item!r}", []
            if not parsed:
                return False, "expected_status cannot be empty", []
            return True, "", parsed
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return False, "expected_status cannot be empty", []
            parsed = []
            for part in text.split(","):
                part = part.strip()
                if not part:
                    continue
                try:
                    parsed.append(int(part))
                except Exception:
                    return False, f"Invalid expected_status value: {part!r}", []
            if not parsed:
                return False, f"Invalid expected_status value: {value!r}", []
            return True, "", parsed
        try:
            return True, "", [int(value)]
        except Exception:
            return False, f"Invalid expected_status: {value!r}", []

    def _decode_http_payload(self, payload: Any, *, headers: Optional[Any] = None) -> str:
        if not payload:
            return ""
        if not isinstance(payload, (bytes, bytearray)):
            try:
                return str(payload)
            except Exception:
                return ""
        encoding = "utf-8"
        if headers is not None:
            try:
                content_type = headers.get_content_charset()
                if content_type:
                    encoding = content_type
            except Exception:
                pass
        try:
            return bytes(payload).decode(encoding, errors="replace")
        except Exception:
            return bytes(payload).decode("utf-8", errors="replace")

    def _http_request_once(
        self,
        method: str,
        url: str,
        headers: Dict[str, str],
        body: Optional[bytes],
        timeout: Optional[int],
    ) -> tuple[bool, Optional[int], str, str]:
        request = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                status = getattr(response, "status", None)
                payload = response.read()
                return True, status, self._decode_http_payload(payload, headers=response.headers), ""
        except urllib.error.HTTPError as exc:
            status = exc.code if isinstance(exc.code, int) else None
            payload = exc.read() if hasattr(exc, "read") else b""
            error_text = self._decode_http_payload(payload, headers=getattr(exc, "headers", None))
            return False, status, error_text, str(exc)
        except urllib.error.URLError as exc:
            return False, None, "", str(exc)
        except Exception as exc:
            return False, None, "", str(exc)

    def _exec_provider_http_request(self, params: Dict[str, Any]) -> tuple[bool, str]:
        """Execute HTTP request via provider."""
        if not isinstance(params, dict):
            return False, "Provider http.params must be an object"

        method = str(params.get("method", "GET")).upper()
        url = str(params.get("url", "")).strip()
        if not url:
            return False, "Provider http.request requires 'url'"

        timeout = self._normalize_provider_timeout(params.get("timeout"), allow_zero=True)
        if timeout is None:
            return False, f"Invalid timeout value: {params.get('timeout')!r}"
        run_timeout = None if timeout in (None, 0) else timeout

        header_ok, header_error, headers = self._coerce_http_headers(params.get("headers"))
        if not header_ok:
            return False, header_error

        body = params.get("body")
        data: Optional[bytes] = None
        if body is not None:
            if isinstance(body, (dict, list)):
                try:
                    data = json.dumps(body).encode("utf-8")
                    headers.setdefault("Content-Type", "application/json")
                except Exception:
                    data = str(body).encode("utf-8")
            elif isinstance(body, bytes):
                data = body
            else:
                data = str(body).encode("utf-8")

        ok, status, body_text, error_text = self._http_request_once(
            method=method,
            url=url,
            headers=headers,
            body=data,
            timeout=run_timeout,
        )
        if ok:
            capture_var = params.get("capture_var")
            if capture_var and isinstance(capture_var, str):
                self.ctx.variables[capture_var] = body_text

            if self.logger:
                self.logger.log_detail("http_request", f"{method} {url}", {
                    "method": method,
                    "url": url,
                    "status": status,
                    "response_len": len(body_text),
                })
            return True, body_text[:500]
        if status is not None:
            message = (
                f"HTTP request failed (status {status}): {body_text[:500] or error_text}"
            )
        else:
            message = f"HTTP request failed: {error_text}"
        return False, message

    def _exec_provider_http_wait(self, params: Dict[str, Any]) -> tuple[bool, str]:
        """Wait for an HTTP endpoint condition."""
        if not isinstance(params, dict):
            return False, "Provider http.params must be an object"

        method = str(params.get("method", "GET")).upper()
        url = str(params.get("url", "")).strip()
        if not url:
            return False, "Provider http.wait_for_status requires 'url'"

        header_ok, header_error, headers = self._coerce_http_headers(params.get("headers"))
        if not header_ok:
            return False, header_error

        status_ok, status_error, expected_statuses = self._coerce_http_statuses(params.get("expected_status", 200))
        if not status_ok:
            return False, status_error
        expected_set = set(expected_statuses)

        expected_text_raw = params.get("expected_text")
        expected_text = None if expected_text_raw is None else str(expected_text_raw)

        request_timeout = self._positive_provider_timeout(
            params.get("request_timeout", params.get("timeout_secs", 10)),
            default=10,
        )
        timeout = self._normalize_provider_timeout(params.get("timeout"), allow_zero=True)
        if timeout is None:
            return False, f"Invalid timeout value: {params.get('timeout')!r}"
        poll_interval = self._normalize_provider_timeout(
            params.get("poll_interval", params.get("interval", 5)),
            allow_zero=True,
        )
        if poll_interval is None:
            return False, f"Invalid poll_interval value: {params.get('poll_interval')!r}"
        if poll_interval <= 0:
            poll_interval = 5

        deadline = time.time() + timeout if timeout else 0
        body = params.get("body")
        body_data: Optional[bytes] = None
        if body is not None:
            if isinstance(body, (dict, list)):
                try:
                    body_data = json.dumps(body).encode("utf-8")
                    headers.setdefault("Content-Type", "application/json")
                except Exception:
                    body_data = str(body).encode("utf-8")
            elif isinstance(body, bytes):
                body_data = body
            else:
                body_data = str(body).encode("utf-8")

        last_status: Optional[int] = None
        last_error = "initial"
        while True:
            ok, status, response_text, error_text = self._http_request_once(
                method=method,
                url=url,
                headers=headers,
                body=body_data,
                timeout=request_timeout,
            )
            last_status = status
            if status is None:
                if error_text:
                    last_error = error_text
            elif status in expected_set and (
                expected_text is None or expected_text in response_text
            ):
                capture_var = params.get("capture_var")
                if capture_var and isinstance(capture_var, str):
                    self.ctx.variables[capture_var] = response_text

                if self.logger:
                    self.logger.log_detail("http_wait", f"{method} {url}", {
                        "method": method,
                        "url": url,
                        "status": status,
                        "expected": sorted(expected_set),
                        "response_len": len(response_text),
                    })
                return True, f"HTTP endpoint matched: status={status}"

            if expected_text is not None and expected_text not in response_text:
                if response_text:
                    last_error = f"status={status}, body={response_text[:500]}"

            if timeout and time.time() >= deadline:
                if timeout == 0:
                    return False, f"Timeout waiting for HTTP endpoint: {url}"
                if last_error:
                    return False, f"Timeout waiting for HTTP condition: {last_error}"
                return False, f"Timeout waiting for HTTP condition: status={last_status}"
            if poll_interval > 0:
                time.sleep(poll_interval)

