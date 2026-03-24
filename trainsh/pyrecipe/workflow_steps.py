"""Workflow and host/storage oriented provider helpers for Python recipes."""

from __future__ import annotations

from typing import Any, Dict, Iterable, Optional


class RecipeProviderWorkflowMixin:
    """Higher-level workflow helpers built on top of generic providers."""

    def git_clone(
        self,
        repo_url: str,
        destination: Optional[str] = None,
        *,
        branch: Optional[str] = None,
        depth: Optional[int] = None,
        auth: Optional[str] = None,
        token_secret: Optional[str] = None,
        timeout: Any = 0,
        host: Optional[str] = None,
        id: Optional[str] = None,
        depends_on: Optional[Iterable[str]] = None,
        step_options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Clone repository with `git clone`."""
        params: Dict[str, Any] = {
            "repo_url": repo_url,
            "timeout": timeout,
        }
        if destination is not None:
            params["destination"] = destination
        if branch is not None:
            params["branch"] = branch
        if depth is not None:
            params["depth"] = depth
        if auth is not None:
            params["auth"] = auth
        if token_secret is not None:
            params["token_secret"] = token_secret
        if host is not None:
            params["host"] = host
        return self.provider(
            "git",
            "clone",
            params=params,
            id=id,
            depends_on=depends_on,
            step_options=step_options,
        )

    def git_pull(
        self,
        directory: str = ".",
        remote: str = "origin",
        branch: Optional[str] = None,
        *,
        timeout: Any = 0,
        host: Optional[str] = None,
        id: Optional[str] = None,
        depends_on: Optional[Iterable[str]] = None,
        step_options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Pull git repository in a directory."""
        params: Dict[str, Any] = {
            "directory": directory,
            "remote": remote,
            "timeout": timeout,
        }
        if branch is not None:
            params["branch"] = branch
        if host is not None:
            params["host"] = host
        return self.provider(
            "git",
            "pull",
            params=params,
            id=id,
            depends_on=depends_on,
            step_options=step_options,
        )

    def host_test(
        self,
        host: str,
        *,
        timeout: Any = 10,
        capture_var: Optional[str] = None,
        id: Optional[str] = None,
        depends_on: Optional[Iterable[str]] = None,
        step_options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Test host connectivity."""
        params: Dict[str, Any] = {"host": host, "timeout": timeout}
        if capture_var is not None:
            params["capture_var"] = capture_var
        return self.provider(
            "host",
            "test",
            params=params,
            id=id,
            depends_on=depends_on,
            step_options=step_options,
        )

    def assert_(
        self,
        condition: str,
        *,
        message: str = "Assertion failed",
        host: Optional[str] = None,
        timeout: Any = 0,
        id: Optional[str] = None,
        depends_on: Optional[Iterable[str]] = None,
        step_options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Evaluate a recipe assertion."""
        params: Dict[str, Any] = {
            "condition": condition,
            "message": message,
            "timeout": timeout,
        }
        if host is not None:
            params["host"] = host
        return self.provider(
            "util",
            "assert",
            params=params,
            id=id,
            depends_on=depends_on,
            step_options=step_options,
        )

    def get_value(
        self,
        source: str,
        target: str,
        *,
        default: Any = "",
        host: Optional[str] = None,
        timeout: Any = 0,
        id: Optional[str] = None,
        depends_on: Optional[Iterable[str]] = None,
        step_options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Get value and assign target variable."""
        params: Dict[str, Any] = {
            "source": source,
            "target": target,
            "default": default,
            "timeout": timeout,
        }
        if host is not None:
            params["host"] = host
        return self.provider(
            "util",
            "get_value",
            params=params,
            id=id,
            depends_on=depends_on,
            step_options=step_options,
        )

    def set_env(
        self,
        name: str,
        value: Any,
        *,
        id: Optional[str] = None,
        depends_on: Optional[Iterable[str]] = None,
        step_options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Set OS environment variable for subsequent steps."""
        return self.provider(
            "util",
            "set_env",
            params={"name": name, "value": "" if value is None else str(value)},
            id=id,
            depends_on=depends_on,
            step_options=step_options,
        )

    def wait_file(
        self,
        path: str,
        *,
        host: Optional[str] = None,
        timeout: Any = "5m",
        poll_interval: Any = "5s",
        id: Optional[str] = None,
        depends_on: Optional[Iterable[str]] = None,
        step_options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Wait for local/remote file existence."""
        params: Dict[str, Any] = {
            "path": path,
            "timeout": timeout,
            "poll_interval": poll_interval,
        }
        if host is not None:
            params["host"] = host
        return self.provider(
            "util",
            "wait_for_file",
            params=params,
            id=id,
            depends_on=depends_on,
            step_options=step_options,
        )

    def wait_for_port(
        self,
        port: int,
        *,
        host: Optional[str] = None,
        host_name: Optional[str] = None,
        timeout: Any = "5m",
        poll_interval: Any = "5s",
        id: Optional[str] = None,
        depends_on: Optional[Iterable[str]] = None,
        step_options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Wait for TCP port to open."""
        params: Dict[str, Any] = {
            "port": port,
            "timeout": timeout,
            "poll_interval": poll_interval,
        }
        if host is not None:
            params["host"] = host
        if host_name is not None:
            params["host_name"] = host_name
        return self.provider(
            "util",
            "wait_for_port",
            params=params,
            id=id,
            depends_on=depends_on,
            step_options=step_options,
        )

    def http_request(
        self,
        method: str,
        url: str,
        *,
        headers: Optional[Dict[str, str]] = None,
        body: Optional[Any] = None,
        timeout: Any = 30,
        capture_var: Optional[str] = None,
        id: Optional[str] = None,
        depends_on: Optional[Iterable[str]] = None,
        step_options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Send HTTP request."""
        return self.provider(
            "http",
            "request",
            params={
                "method": method,
                "url": url,
                "headers": headers or {},
                "body": body,
                "timeout": timeout,
                "capture_var": capture_var,
            },
            id=id,
            depends_on=depends_on,
            step_options=step_options,
        )

    def hf_download(
        self,
        repo_id: str,
        *,
        local_dir: Optional[str] = None,
        filename: Optional[str] = None,
        filenames: Optional[Iterable[str]] = None,
        revision: Optional[str] = None,
        token: Optional[str] = None,
        host: Optional[str] = None,
        id: Optional[str] = None,
        depends_on: Optional[Iterable[str]] = None,
        step_options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Download files from Hugging Face."""
        params: Dict[str, Any] = {"repo_id": repo_id}
        if local_dir is not None:
            params["local_dir"] = local_dir
        if revision is not None:
            params["revision"] = revision
        if token is not None:
            params["token"] = token
        if filename is not None:
            params["filename"] = filename
        if filenames is not None:
            params["filenames"] = list(filenames)
        if host is not None:
            params["host"] = host
        return self.provider(
            "util",
            "hf_download",
            params=params,
            id=id,
            depends_on=depends_on,
            step_options=step_options,
        )

    def fetch_exchange_rates(
        self,
        *,
        id: Optional[str] = None,
        depends_on: Optional[Iterable[str]] = None,
        step_options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Fetch exchange rates."""
        return self.provider(
            "util",
            "fetch_exchange_rates",
            params={},
            id=id,
            depends_on=depends_on,
            step_options=step_options,
        )

    def calculate_cost(
        self,
        *,
        vast: bool = False,
        host_id: Optional[str] = None,
        gpu_hourly_usd: Any = 0,
        storage_gb: Any = 0,
        currency: str = "USD",
        id: Optional[str] = None,
        depends_on: Optional[Iterable[str]] = None,
        step_options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Calculate cost estimate."""
        return self.provider(
            "util",
            "calculate_cost",
            params={
                "vast": bool(vast),
                "host_id": host_id,
                "gpu_hourly_usd": gpu_hourly_usd,
                "storage_gb": storage_gb,
                "currency": currency,
            },
            id=id,
            depends_on=depends_on,
            step_options=step_options,
        )

    def ssh_command(
        self,
        host: str,
        command: str,
        *,
        timeout: Any = 0,
        id: Optional[str] = None,
        depends_on: Optional[Iterable[str]] = None,
        step_options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Execute one shell command on a host."""
        return self.provider(
            "util",
            "ssh_command",
            params={
                "host": host,
                "command": command,
                "timeout": timeout,
            },
            id=id,
            depends_on=depends_on,
            step_options=step_options,
        )

    def ssh(
        self,
        host: str,
        command: str,
        *,
        timeout: Any = 0,
        id: Optional[str] = None,
        depends_on: Optional[Iterable[str]] = None,
        step_options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Alias for :meth:`ssh_command`."""
        return self.ssh_command(
            host,
            command,
            timeout=timeout,
            id=id,
            depends_on=depends_on,
            step_options=step_options,
        )

    def uv_run(
        self,
        command: str,
        *,
        packages: Optional[Iterable[str]] = None,
        host: Optional[str] = None,
        timeout: Any = 300,
        id: Optional[str] = None,
        depends_on: Optional[Iterable[str]] = None,
        step_options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Run command via `uv run`."""
        params: Dict[str, Any] = {"command": command, "timeout": timeout}
        if host is not None:
            params["host"] = host
        if packages is not None:
            params["packages"] = list(packages)
        return self.provider(
            "util",
            "uv_run",
            params=params,
            id=id,
            depends_on=depends_on,
            step_options=step_options,
        )
