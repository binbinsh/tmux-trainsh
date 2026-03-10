"""HTTP helpers for Python recipes."""

from __future__ import annotations

from typing import Any, Dict, Iterable, Optional


class RecipeProviderNetworkMixin:
    """HTTP provider helpers and lightweight sensor-style waits."""

    def _normalize_http_headers(self, headers: Optional[Dict[str, Any]]) -> Optional[Dict[str, str]]:
        if headers is None:
            return None
        if not isinstance(headers, dict):
            return None
        normalized: Dict[str, str] = {}
        for key, value in headers.items():
            if key is None:
                continue
            normalized[str(key)] = "" if value is None else str(value)
        return normalized

    def http_get(
        self,
        url: str,
        *,
        headers: Optional[Dict[str, Any]] = None,
        timeout: Any = 30,
        capture_var: Optional[str] = None,
        id: Optional[str] = None,
        depends_on: Optional[Iterable[str]] = None,
        step_options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Send HTTP GET request."""
        return self.provider(
            "http",
            "get",
            params={
                "method": "GET",
                "url": url,
                "headers": self._normalize_http_headers(headers),
                "timeout": timeout,
                "capture_var": capture_var,
            },
            id=id,
            depends_on=depends_on,
            step_options=step_options,
        )

    def http_post(
        self,
        url: str,
        *,
        headers: Optional[Dict[str, Any]] = None,
        body: Optional[Any] = None,
        json_body: Optional[Any] = None,
        timeout: Any = 30,
        capture_var: Optional[str] = None,
        id: Optional[str] = None,
        depends_on: Optional[Iterable[str]] = None,
        step_options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Send HTTP POST request."""
        payload = json_body if json_body is not None else body
        normalized_headers = self._normalize_http_headers(headers)
        if json_body is not None and normalized_headers is not None:
            normalized_headers.setdefault("Content-Type", "application/json")

        return self.provider(
            "http",
            "post",
            params={
                "method": "POST",
                "url": url,
                "headers": normalized_headers,
                "body": payload,
                "timeout": timeout,
                "capture_var": capture_var,
            },
            id=id,
            depends_on=depends_on,
            step_options=step_options,
        )

    def http_put(
        self,
        url: str,
        *,
        headers: Optional[Dict[str, Any]] = None,
        body: Optional[Any] = None,
        json_body: Optional[Any] = None,
        timeout: Any = 30,
        capture_var: Optional[str] = None,
        id: Optional[str] = None,
        depends_on: Optional[Iterable[str]] = None,
        step_options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Send HTTP PUT request."""
        payload = json_body if json_body is not None else body
        normalized_headers = self._normalize_http_headers(headers)
        if json_body is not None and normalized_headers is not None:
            normalized_headers.setdefault("Content-Type", "application/json")

        return self.provider(
            "http",
            "put",
            params={
                "method": "PUT",
                "url": url,
                "headers": normalized_headers,
                "body": payload,
                "timeout": timeout,
                "capture_var": capture_var,
            },
            id=id,
            depends_on=depends_on,
            step_options=step_options,
        )

    def http_delete(
        self,
        url: str,
        *,
        headers: Optional[Dict[str, Any]] = None,
        body: Optional[Any] = None,
        timeout: Any = 30,
        capture_var: Optional[str] = None,
        id: Optional[str] = None,
        depends_on: Optional[Iterable[str]] = None,
        step_options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Send HTTP DELETE request."""
        return self.provider(
            "http",
            "delete",
            params={
                "method": "DELETE",
                "url": url,
                "headers": self._normalize_http_headers(headers),
                "body": body,
                "timeout": timeout,
                "capture_var": capture_var,
            },
            id=id,
            depends_on=depends_on,
            step_options=step_options,
        )

    def http_head(
        self,
        url: str,
        *,
        headers: Optional[Dict[str, Any]] = None,
        timeout: Any = 30,
        capture_var: Optional[str] = None,
        id: Optional[str] = None,
        depends_on: Optional[Iterable[str]] = None,
        step_options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Send HTTP HEAD request."""
        return self.provider(
            "http",
            "head",
            params={
                "method": "HEAD",
                "url": url,
                "headers": self._normalize_http_headers(headers),
                "timeout": timeout,
                "capture_var": capture_var,
            },
            id=id,
            depends_on=depends_on,
            step_options=step_options,
        )

    def http_wait_for_status(
        self,
        url: str,
        *,
        method: str = "GET",
        headers: Optional[Dict[str, Any]] = None,
        body: Optional[Any] = None,
        json_body: Optional[Any] = None,
        expected_status: int | Iterable[int] | str = 200,
        expected_text: Optional[str] = None,
        timeout: Any = "5m",
        poll_interval: Any = "5s",
        request_timeout: Any = 10,
        capture_var: Optional[str] = None,
        id: Optional[str] = None,
        depends_on: Optional[Iterable[str]] = None,
        step_options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Wait until an HTTP endpoint matches status/text conditions."""
        payload = json_body if json_body is not None else body
        normalized_headers = self._normalize_http_headers(headers)
        if json_body is not None and normalized_headers is not None:
            normalized_headers.setdefault("Content-Type", "application/json")

        return self.provider(
            "http",
            "wait_for_status",
            params={
                "method": method,
                "url": url,
                "headers": normalized_headers,
                "body": payload,
                "expected_status": expected_status,
                "expected_text": expected_text,
                "timeout": timeout,
                "poll_interval": poll_interval,
                "request_timeout": request_timeout,
                "capture_var": capture_var,
            },
            id=id,
            depends_on=depends_on,
                step_options=step_options,
            )

    def http_request_json(
        self,
        url: str,
        method: str = "POST",
        *,
        body: Optional[Any] = None,
        json_body: Optional[Any] = None,
        headers: Optional[Dict[str, Any]] = None,
        timeout: Any = 30,
        capture_var: Optional[str] = None,
        id: Optional[str] = None,
        depends_on: Optional[Iterable[str]] = None,
        step_options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """JSON-friendly HTTP request alias."""
        payload = json_body if json_body is not None else body
        normalized_headers = self._normalize_http_headers(headers)
        if json_body is not None and normalized_headers is not None:
            normalized_headers.setdefault("Content-Type", "application/json")
        return self.provider(
            "http",
            "request_json",
            params={
                "method": method,
                "url": url,
                "headers": normalized_headers,
                "body": payload,
                "timeout": timeout,
                "capture_var": capture_var,
            },
            id=id,
            depends_on=depends_on,
            step_options=step_options,
        )

    def http_post_json(
        self,
        url: str,
        *,
        body: Optional[Any] = None,
        json_body: Optional[Any] = None,
        headers: Optional[Dict[str, Any]] = None,
        timeout: Any = 30,
        capture_var: Optional[str] = None,
        id: Optional[str] = None,
        depends_on: Optional[Iterable[str]] = None,
        step_options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """JSON helper for POST requests."""
        return self.http_request_json(
            url,
            method="POST",
            body=body,
            json_body=json_body,
            headers=headers,
            timeout=timeout,
            capture_var=capture_var,
            id=id,
            depends_on=depends_on,
            step_options=step_options,
        )

    def http_put_json(
        self,
        url: str,
        *,
        body: Optional[Any] = None,
        json_body: Optional[Any] = None,
        headers: Optional[Dict[str, Any]] = None,
        timeout: Any = 30,
        capture_var: Optional[str] = None,
        id: Optional[str] = None,
        depends_on: Optional[Iterable[str]] = None,
        step_options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """JSON helper for PUT requests."""
        return self.http_request_json(
            url,
            method="PUT",
            body=body,
            json_body=json_body,
            headers=headers,
            timeout=timeout,
            capture_var=capture_var,
            id=id,
            depends_on=depends_on,
            step_options=step_options,
        )

    def http_delete_json(
        self,
        url: str,
        *,
        body: Optional[Any] = None,
        headers: Optional[Dict[str, Any]] = None,
        timeout: Any = 30,
        capture_var: Optional[str] = None,
        id: Optional[str] = None,
        depends_on: Optional[Iterable[str]] = None,
        step_options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """JSON helper for DELETE requests."""
        return self.http_request_json(
            url,
            method="DELETE",
            body=body,
            headers=headers,
            timeout=timeout,
            capture_var=capture_var,
            id=id,
            depends_on=depends_on,
            step_options=step_options,
        )

    def http_wait(
        self,
        url: str,
        *,
        expected_status: int | Iterable[int] | str = 200,
        expected_text: Optional[str] = None,
        timeout: Any = "5m",
        poll_interval: Any = "5s",
        request_timeout: Any = 10,
        id: Optional[str] = None,
        depends_on: Optional[Iterable[str]] = None,
        step_options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Alias for :meth:`http_wait_for_status`."""
        return self.http_wait_for_status(
            url,
            method="GET",
            expected_status=expected_status,
            expected_text=expected_text,
            timeout=timeout,
            poll_interval=poll_interval,
            request_timeout=request_timeout,
            id=id,
            depends_on=depends_on,
            step_options=step_options,
        )

    def http_sensor(
        self,
        url: str,
        *,
        method: str = "GET",
        expected_status: int | Iterable[int] | str = 200,
        expected_text: Optional[str] = None,
        headers: Optional[Dict[str, Any]] = None,
        body: Optional[Any] = None,
        json_body: Optional[Any] = None,
        timeout: Any = "5m",
        poll_interval: Any = "5s",
        request_timeout: Any = 10,
        capture_var: Optional[str] = None,
        id: Optional[str] = None,
        depends_on: Optional[Iterable[str]] = None,
        step_options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Airflow-like sensor name for HTTP status polling."""
        payload = json_body if json_body is not None else body
        normalized_headers = self._normalize_http_headers(headers)
        if json_body is not None and normalized_headers is not None:
            normalized_headers.setdefault("Content-Type", "application/json")

        return self.provider(
            "http",
            "http_sensor",
            params={
                "method": method,
                "url": url,
                "headers": normalized_headers,
                "body": payload,
                "expected_status": expected_status,
                "expected_text": expected_text,
                "timeout": timeout,
                "poll_interval": poll_interval,
                "request_timeout": request_timeout,
                "capture_var": capture_var,
            },
            id=id,
            depends_on=depends_on,
            step_options=step_options,
        )
