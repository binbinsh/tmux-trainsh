"""Shell-like provider operations and condition evaluation helpers."""

from __future__ import annotations

import os
import shlex
import socket
import subprocess
import time
from datetime import datetime
from typing import Any, Dict, List

from ..services.git_auth import (
    build_git_clone_command,
    build_remote_git_auth_command,
    is_plain_github_repo_url,
    materialize_git_askpass_script,
    normalize_git_auth_mode,
)
from ..services.secret_materialize import materialize_secret_file
from ..utils.notifier import normalize_channels, parse_bool
from .executor_utils import _build_ssh_args, _host_from_ssh_spec, _resolve_vast_host


class ExecutorProviderShellOpsMixin:
    def _exec_provider_shell(self, params: Dict[str, Any]) -> tuple[bool, str]:
        """Execute shell command in provider mode."""
        if not isinstance(params, dict):
            return False, "Provider shell params must be an object"

        command = str(params.get("command", "")).strip()
        if not command:
            return False, "Provider shell requires 'command'"
        command = self._interpolate(command)

        timeout = self._normalize_provider_timeout(params.get("timeout"), allow_zero=True)
        run_timeout = None if timeout in (None, 0) else timeout
        if timeout is None:
            return False, f"Invalid timeout value: {params.get('timeout')!r}"

        cwd = params.get("cwd")
        if cwd is not None:
            cwd = os.path.expanduser(str(cwd))

        shell_env = dict(os.environ)
        env = params.get("env")
        if env is not None:
            if not isinstance(env, dict):
                return False, "Provider shell env must be an object"
            for key, value in env.items():
                shell_env[str(key)] = str(value)

        host = self._provider_host(params.get("host", "local"))
        run_command = command
        if host != "local" and cwd is not None:
            run_command = f"cd {shlex.quote(str(cwd))} && ({command})"

        start = datetime.now()
        try:
            if host == "local":
                result = subprocess.run(
                    command,
                    shell=True,
                    cwd=cwd,
                    env=shell_env,
                    capture_output=True,
                    text=True,
                    timeout=run_timeout,
                )
            else:
                ssh_args = _build_ssh_args(host, command=run_command, tty=False)
                result = subprocess.run(
                    ssh_args,
                    capture_output=True,
                    text=True,
                    timeout=run_timeout,
                )

            duration_ms = int((datetime.now() - start).total_seconds() * 1000)
            output = result.stdout or result.stderr

            if self.logger:
                self.logger.log_ssh(
                    host,
                    command,
                    result.returncode,
                    result.stdout,
                    result.stderr,
                    duration_ms,
                )
        except subprocess.TimeoutExpired:
            return False, f"Shell command timed out after {timeout}s"
        except Exception as exc:
            return False, str(exc)

        capture_var = params.get("capture_var")
        if capture_var:
            if isinstance(capture_var, str):
                self.ctx.variables[capture_var] = output

        return result.returncode == 0, output or (f"Shell command completed ({duration_ms}ms)" if result.returncode == 0 else "")

    def _eval_condition(self, condition: str, *, host: str = "local") -> tuple[bool, str]:
        """Evaluate simple condition expression."""
        condition = str(condition).strip()
        if not condition:
            return False, "Condition is empty"

        if condition.startswith("var:"):
            body = condition[4:]
            if "==" in body:
                name, expected = [item.strip() for item in body.split("==", 1)]
                actual = str(self.ctx.variables.get(name, ""))
                return actual == expected, f"{name} == {expected}"
            return bool(self.ctx.variables.get(body, "")), f"var:{body} is set"

        if condition.startswith("env:"):
            body = condition[4:]
            if "==" in body:
                name, expected = [item.strip() for item in body.split("==", 1)]
                actual = os.environ.get(name, "")
                return str(actual) == expected, f"{name} == {expected}"
            return bool(os.environ.get(body, "")), f"env:{body} is set"

        if condition.startswith("file_exists:"):
            path = self._interpolate(condition[len("file_exists:") :].strip())
            if host == "local":
                return os.path.exists(os.path.expanduser(path)), f"file_exists:{path}"
            ok, output = self._exec_provider_shell(
                {
                    "command": f"test -e {shlex.quote(path)} && echo exists",
                    "host": host,
                    "timeout": 30,
                }
            )
            return ok and "exists" in output, f"file_exists:{path}"

        if condition.startswith("file_contains:"):
            remain = condition[len("file_contains:") :].strip()
            path, sep, expected = remain.partition(":")
            path = self._interpolate(path.strip())
            expected = expected.strip()
            if not path:
                return False, "Condition file path is empty"
            if not sep or not expected:
                return False, "Condition file_contains requires pattern"

            if host == "local":
                target = os.path.expanduser(path)
                if not os.path.isfile(target):
                    return False, f"File not found: {target}"
                with open(target, "r", encoding="utf-8", errors="replace") as f:
                    return expected in f.read(), f"file_contains:{path} has expected text"

            ok, output = self._exec_provider_shell(
                {
                    "command": (
                        f"test -f {shlex.quote(path)} && "
                        f"grep -qF {shlex.quote(expected)} {shlex.quote(path)} && echo found"
                    ),
                    "host": host,
                    "timeout": 30,
                }
            )
            return ok and "found" in output, f"file_contains:{path} has expected text"

        if condition.startswith("storage_exists:"):
            raw_spec = condition[len("storage_exists:") :].strip()
            if not raw_spec:
                return False, "Condition storage_exists is empty"
            storage_ref, _, path = raw_spec.partition(":")
            storage_ref = storage_ref.strip()
            if not storage_ref:
                return False, "Condition storage_exists missing storage id"
            storage_ref = storage_ref[1:] if storage_ref.startswith("@") else storage_ref
            path = self._interpolate(path.strip())
            if path is None:
                path = ""
            ok, _ = self._exec_provider_storage_exists({"storage": storage_ref, "path": path})
            return ok, f"storage_exists:{storage_ref}:{path}"

        if condition.startswith("command:"):
            command = self._interpolate(condition[8:].strip())
            if not command:
                return False, "Condition command is empty"
            ok, _ = self._exec_provider_shell(
                {
                    "command": command,
                    "host": host,
                    "timeout": 30,
                }
            )
            return ok, f"command:{command}"

        if condition.startswith("command_output:"):
            remain = condition[len("command_output:") :].strip()
            command, sep, expected = remain.partition(":")
            command = self._interpolate(command.strip())
            expected = expected.strip()
            if not command:
                return False, "Condition command_output command is empty"
            if not sep or not expected:
                return False, "Condition command_output requires expected text"
            ok, output = self._exec_provider_shell(
                {
                    "command": command,
                    "host": host,
                    "timeout": 30,
                }
            )
            return ok and (expected in output), f"command_output:{command} contains text"

        if condition.startswith("host_online:"):
            host_ref = condition[len("host_online:") :].strip()
            if not host_ref:
                return False, "Condition host_online requires host"
            target = self._provider_host(host_ref)
            if target == "local":
                return True, "local is online"
            return self._verify_ssh_connection(target, timeout=10), f"host_online:{target}"

        return False, f"Unsupported condition: {condition!r}"

    def _exec_provider_git_clone(self, params: Dict[str, Any]) -> tuple[bool, str]:
        """Clone a git repository via provider."""
        if not isinstance(params, dict):
            return False, "Provider git.clone params must be an object"

        repo_url = self._interpolate(str(params.get("repo_url", params.get("repo", "")))).strip()
        destination = self._interpolate(str(params.get("destination", params.get("path", "")))).strip()
        if not repo_url:
            return False, "Provider git.clone requires 'repo_url' (or 'repo')"

        branch = str(params.get("branch", "")).strip()
        depth = params.get("depth")
        host = self._provider_host(params.get("host", "local"))
        timeout = self._positive_provider_timeout(
            params.get("timeout", params.get("timeout_secs", 0)),
            default=300,
        )
        depth_text = "" if depth is None else str(depth).strip()
        try:
            auth_mode = normalize_git_auth_mode(params.get("auth"))
        except ValueError as exc:
            return False, str(exc)
        token_secret = self._interpolate(str(params.get("token_secret", "GITHUB_TOKEN"))).strip() or "GITHUB_TOKEN"
        command = build_git_clone_command(
            repo_url,
            destination,
            branch=branch,
            depth=depth_text,
        )

        token_auth_error = self._validate_github_clone_auth(repo_url, auth_mode)
        if token_auth_error:
            return False, token_auth_error

        token_state = self._load_git_clone_token(
            repo_url=repo_url,
            auth_mode=auth_mode,
            token_secret=token_secret,
        )
        if token_state["error"]:
            return False, str(token_state["error"])
        if token_state["token_file"] and token_state["token_text"]:
            return self._exec_provider_github_clone_with_token(
                command=command,
                host=host,
                timeout=timeout,
                token_file=str(token_state["token_file"]),
                token_text=str(token_state["token_text"]),
            )

        return self._exec_provider_shell({"command": command, "host": host, "timeout": timeout})

    def _validate_github_clone_auth(self, repo_url: str, auth_mode: str) -> str:
        """Validate explicit git clone auth requirements."""
        if auth_mode != "github_token":
            return ""
        if not is_plain_github_repo_url(repo_url):
            return (
                "Provider git.clone auth=github_token currently supports "
                "plain https://github.com/OWNER/REPO(.git) URLs only"
            )
        return ""

    def _load_git_clone_token(
        self,
        *,
        repo_url: str,
        auth_mode: str,
        token_secret: str,
    ) -> Dict[str, str]:
        """Resolve one token file/text pair for git clone auth."""
        state = {"token_file": "", "token_text": "", "error": ""}
        if auth_mode == "plain":
            return state
        if not is_plain_github_repo_url(repo_url):
            return state

        token_file = materialize_secret_file(token_secret, suffix=".token")
        if not token_file or not os.path.exists(token_file):
            if auth_mode == "github_token":
                state["error"] = f"Provider git.clone requires secret {token_secret} for auth=github_token"
            return state

        try:
            with open(token_file, "r", encoding="utf-8", errors="replace") as handle:
                token_text = handle.read().strip()
        except OSError as exc:
            if auth_mode == "github_token":
                state["error"] = str(exc)
            return state

        if not token_text:
            if auth_mode == "github_token":
                state["error"] = f"Provider git.clone secret {token_secret} is empty"
            return state

        state["token_file"] = token_file
        state["token_text"] = token_text
        return state

    def _exec_provider_github_clone_with_token(
        self,
        *,
        command: str,
        host: str,
        timeout: int,
        token_file: str,
        token_text: str,
    ) -> tuple[bool, str]:
        """Run one authenticated GitHub clone without mutating URLs or git config."""
        run_timeout = None if timeout in (None, 0) else timeout
        start = datetime.now()
        try:
            if host == "local":
                env = dict(os.environ)
                env["GIT_ASKPASS"] = materialize_git_askpass_script()
                env["GIT_TERMINAL_PROMPT"] = "0"
                env["TRAINSH_GIT_PASSWORD_FILE"] = token_file
                result = subprocess.run(
                    command,
                    shell=True,
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=run_timeout,
                )
            else:
                remote_command = build_remote_git_auth_command(command)
                ssh_args = _build_ssh_args(host, command=remote_command, tty=False)
                token_input = token_text if token_text.endswith("\n") else f"{token_text}\n"
                result = subprocess.run(
                    ssh_args,
                    input=token_input,
                    capture_output=True,
                    text=True,
                    timeout=run_timeout,
                )
            duration_ms = int((datetime.now() - start).total_seconds() * 1000)
            output = result.stdout or result.stderr
            if self.logger:
                self.logger.log_ssh(
                    host,
                    command,
                    result.returncode,
                    result.stdout,
                    result.stderr,
                    duration_ms,
                )
            return result.returncode == 0, output or (
                f"Shell command completed ({duration_ms}ms)" if result.returncode == 0 else ""
            )
        except subprocess.TimeoutExpired:
            return False, f"Shell command timed out after {timeout}s"
        except Exception as exc:
            return False, str(exc)

    def _exec_provider_git_pull(self, params: Dict[str, Any]) -> tuple[bool, str]:
        """Pull git repository changes via provider."""
        if not isinstance(params, dict):
            return False, "Provider git.pull params must be an object"

        directory = self._interpolate(str(params.get("directory", "."))).strip() or "."
        remote = self._interpolate(str(params.get("remote", "origin"))).strip() or "origin"
        branch = self._interpolate(str(params.get("branch", ""))).strip()
        command = "git -C " + shlex.quote(directory) + f" pull {shlex.quote(remote)}"
        if branch:
            command += f" {shlex.quote(branch)}"

        host = self._provider_host(params.get("host", "local"))
        return self._exec_provider_shell(
            {
                "command": command,
                "host": host,
                "timeout": self._positive_provider_timeout(params.get("timeout", params.get("timeout_secs", 0)), default=300),
            }
        )

    def _exec_provider_host_test(self, params: Dict[str, Any]) -> tuple[bool, str]:
        """Test SSH connectivity for a host."""
        if not isinstance(params, dict):
            return False, "Provider host.test params must be an object"

        host = self._provider_host(params.get("host"))
        if host == "local":
            return True, "Host local is local"

        timeout = self._positive_provider_timeout(params.get("timeout", params.get("timeout_secs", 10)), default=10)
        ok = self._verify_ssh_connection(host, timeout=timeout)
        if not ok:
            return False, f"Failed to connect to host {host}"

        capture_var = params.get("capture_var")
        if capture_var:
            self.ctx.variables[str(capture_var)] = "1"
        return True, f"Host {host} is reachable"

    def _exec_provider_assert(self, params: Dict[str, Any]) -> tuple[bool, str]:
        """Assert a condition via provider."""
        if not isinstance(params, dict):
            return False, "Provider util.assert params must be an object"

        condition = self._interpolate(str(params.get("condition", ""))).strip()
        if not condition:
            return False, "Provider util.assert requires 'condition'"
        message = str(params.get("message", "Assertion failed"))

        host = self._provider_host(params.get("host", "local"))

        if condition.startswith("var:"):
            expr = condition[4:].strip()
            if "==" in expr:
                var_name, expected = [item.strip() for item in expr.split("==", 1)]
                actual = self.ctx.variables.get(var_name, "")
                if actual == expected:
                    return True, f"Assertion passed: {var_name} == {expected}"
                return False, f"{message}: {var_name} expected {expected}, got {actual}"

            if self.ctx.variables.get(expr, ""):
                return True, f"Assertion passed: {expr} is set"
            return False, f"{message}: {expr} is not set"

        if condition.startswith("file:") or condition.startswith("file_exists:"):
            filepath = self._interpolate(condition.split(":", 1)[1]).strip()
            if host == "local":
                if os.path.exists(os.path.expanduser(filepath)):
                    return True, f"Assertion passed: file exists {filepath}"
                return False, f"{message}: file not found {filepath}"

            ok, output = self._exec_provider_shell(
                {
                    "command": f"test -f {shlex.quote(filepath)} && echo exists",
                    "host": host,
                    "timeout": 30,
                }
            )
            if ok and "exists" in output:
                return True, f"Assertion passed: file exists {filepath}"
            return False, f"{message}: file not found {filepath}"

        if condition.startswith("command:"):
            cmd = self._interpolate(condition.split(":", 1)[1]).strip()
            ok, output = self._exec_provider_shell(
                {
                    "command": cmd,
                    "host": host,
                    "timeout": self._positive_provider_timeout(
                        params.get("timeout", params.get("timeout_secs", 0)),
                        default=120,
                    ),
                }
            )
            if ok:
                return True, f"Assertion passed: {output}".strip() or "Assertion passed"
            return False, f"{message}: command failed"

        return False, f"Unsupported assertion condition: {condition!r}"

    def _exec_provider_get_value(self, params: Dict[str, Any]) -> tuple[bool, str]:
        """Get value from env/secret/var/command and store in recipe variable."""
        if not isinstance(params, dict):
            return False, "Provider util.get_value params must be an object"

        target = str(params.get("target", params.get("name", ""))).strip()
        if not target:
            return False, "Provider util.get_value requires 'target' (or 'name')"
        source = self._interpolate(str(params.get("source", ""))).strip()
        if not source:
            return False, "Provider util.get_value requires 'source'"
        default_value = str(params.get("default", ""))

        if source.startswith("env:"):
            value = os.environ.get(source[4:], default_value)
        elif source.startswith("secret:"):
            value = self.secrets.get(source[7:]) or default_value
        elif source.startswith("var:"):
            value = self.ctx.variables.get(source[4:], default_value)
        elif source.startswith("command:"):
            host = self._provider_host(params.get("host", "local"))
            command = self._interpolate(source[8:]).strip()
            ok, output = self._exec_provider_shell(
                {
                    "command": command,
                    "host": host,
                    "timeout": self._positive_provider_timeout(params.get("timeout", params.get("timeout_secs", 0)), default=120),
                }
            )
            if not ok:
                return False, f"Failed to get command output: {command}"
            value = output.strip()
        else:
            return False, f"Unsupported source: {source!r}"

        self.ctx.variables[target] = "" if value is None else str(value)
        return True, f"Set {target} from {source}"

    def _exec_provider_set_env(self, params: Dict[str, Any]) -> tuple[bool, str]:
        """Set environment variable."""
        if not isinstance(params, dict):
            return False, "Provider util.set_env params must be an object"

        name = str(params.get("name", "")).strip()
        if not name:
            return False, "Provider util.set_env requires 'name'"
        value = self._interpolate(str(params.get("value", "")))
        os.environ[name] = value
        return True, f"Set environment variable {name}"

    def _exec_provider_wait_for_file(self, params: Dict[str, Any]) -> tuple[bool, str]:
        """Wait for a file to exist."""
        if not isinstance(params, dict):
            return False, "Provider util.wait_for_file params must be an object"

        path = self._interpolate(str(params.get("path", ""))).strip()
        if not path:
            return False, "Provider util.wait_for_file requires 'path'"
        host = self._provider_host(params.get("host", "local"))
        timeout = self._positive_provider_timeout(
            params.get("timeout", params.get("timeout_secs", 300)),
            default=300,
        )
        poll_interval = self._positive_provider_timeout(
            params.get("poll_interval", params.get("interval", 5)),
            default=5,
        )

        end_time = time.time() + timeout
        check_cmd = f"test -f {shlex.quote(path)} && echo exists"
        while time.time() < end_time:
            if host == "local":
                if os.path.exists(os.path.expanduser(path)):
                    return True, f"File found: {path}"
            else:
                ok, output = self._exec_provider_shell(
                    {
                        "command": check_cmd,
                        "host": host,
                        "timeout": self._positive_provider_timeout(
                            poll_interval,
                            default=5,
                        ),
                    }
                )
                if ok and "exists" in output:
                    return True, f"File found: {path}"
            time.sleep(poll_interval)
        return False, f"Timeout waiting for file: {path}"

    def _exec_provider_wait_for_port(self, params: Dict[str, Any]) -> tuple[bool, str]:
        """Wait for a TCP port to open."""
        if not isinstance(params, dict):
            return False, "Provider util.wait_for_port params must be an object"

        port_raw = params.get("port")
        if str(port_raw).strip() == "":
            return False, "Provider util.wait_for_port requires 'port'"
        try:
            port = int(port_raw)
        except Exception:
            return False, "Provider util.wait_for_port port must be integer"
        if port <= 0:
            return False, "Provider util.wait_for_port port must be positive"

        host = self._provider_host(params.get("host", "local"))
        explicit_host_name = self._interpolate(str(params.get("host_name", ""))).strip()
        check_host = explicit_host_name or "localhost"
        timeout = self._positive_provider_timeout(
            params.get("timeout", params.get("timeout_secs", 300)),
            default=300,
        )
        poll_interval = self._positive_provider_timeout(
            params.get("poll_interval", params.get("interval", 5)),
            default=5,
        )

        end_time = time.time() + timeout
        while time.time() < end_time:
            if host == "local":
                try:
                    with socket.create_connection((check_host, port), timeout=2):
                        return True, f"Port {port} is open on {check_host}"
                except OSError:
                    pass
            else:
                # Check from remote host context using target's shell.
                remote_host = _host_from_ssh_spec(host)
                host_to_check = explicit_host_name or remote_host.hostname or check_host
                ok, output = self._exec_provider_shell(
                    {
                        "command": f"nc -z {shlex.quote(host_to_check)} {int(port)} 2>/dev/null && echo open || true",
                        "host": host,
                        "timeout": self._positive_provider_timeout(
                            poll_interval,
                            default=5,
                        ),
                    }
                )
                if ok and "open" in output:
                    return True, f"Port {port} is open on {host_to_check}"

            time.sleep(poll_interval)

        return False, f"Timeout waiting for port {port} on {check_host}"
