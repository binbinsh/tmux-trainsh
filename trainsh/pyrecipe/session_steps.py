"""Session-oriented helpers for Python recipes."""

from __future__ import annotations

import json
import shlex
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from textwrap import dedent
from typing import Any, Dict, Iterable, Optional, TYPE_CHECKING

from ..core.recipe_models import RecipeStepModel, StepType
from .authoring_support import normalize_after, split_step_call
from .models import PythonRecipeError

if TYPE_CHECKING:
    from .base import RecipeSpecCore


def official_uv_install_command(*, force: bool = False) -> str:
    """Build a shell command that installs uv via the official Astral script."""
    if force:
        return (
            'curl -LsSf https://astral.sh/uv/install.sh | sh && '
            'export PATH="$HOME/.local/bin:$PATH" && hash -r && uv --version'
        )
    return (
        'if ! command -v uv >/dev/null 2>&1 && [ ! -x "$HOME/.local/bin/uv" ]; then '
        'curl -LsSf https://astral.sh/uv/install.sh | sh; '
        'fi && export PATH="$HOME/.local/bin:$PATH" && hash -r && uv --version'
    )


@dataclass(frozen=True)
class RecipeSessionRef:
    """A lightweight proxy bound to one tmux session/window name."""

    recipe: "RecipeSpecCore"
    name: str
    open_step_id: Optional[str] = None
    host_ref: Optional[str] = None
    default_depends_on: tuple[str, ...] = field(default_factory=tuple)
    default_cwd: Optional[str] = None
    default_env: dict[str, Any] = field(default_factory=dict)
    close_on_exit: bool = False
    close_step_options: Optional[Dict[str, Any]] = None
    _linear_cm: Any = field(default=None, init=False, repr=False, compare=False)

    def _merge_depends(self, depends_on: Optional[Iterable[str]]) -> list[str]:
        merged: list[str] = []
        seen = set()
        for item in [*self.default_depends_on, *(depends_on or [])]:
            dep = str(item).strip()
            if not dep or dep in seen:
                continue
            seen.add(dep)
            merged.append(dep)
        return merged

    def _require_host_ref(self) -> str:
        host_ref = str(self.host_ref or "").strip()
        if not host_ref:
            raise PythonRecipeError(
                "session transfer helpers require a session created with host=..."
            )
        return host_ref

    def __enter__(self) -> "RecipeSessionRef":
        cm = self.recipe._linear(depends_on=list(self.default_depends_on))
        cm.__enter__()
        object.__setattr__(self, "_linear_cm", cm)
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        cm = getattr(self, "_linear_cm", None)
        result = False
        try:
            if cm is not None and self.close_on_exit:
                self.close(step_options=self.close_step_options)
        finally:
            if cm is not None:
                object.__setattr__(self, "_linear_cm", None)
                result = bool(cm.__exit__(exc_type, exc, tb))
        return result

    def remote_path(self, value: Any) -> str:
        """Resolve one remote endpoint on this session's host."""
        return f"@{self._require_host_ref()}:{self.recipe.resolve_endpoint(value)}"

    def after(self, *dependencies: Any) -> "RecipeSessionRef":
        """Return a new session ref with extra default dependencies.

        This only affects future steps created from the returned session ref.
        The session open step is already registered, so retroactively wiring it
        to later work can create immediate dependency cycles.
        """
        normalized: list[str] = []
        for item in dependencies:
            normalized.extend(normalize_after(item) or [])
        return replace(
            self,
            default_depends_on=tuple(self._merge_depends(normalized)),
        )

    def cd(self, path: Optional[str]) -> "RecipeSessionRef":
        """Return a new session ref with a default working directory."""
        cwd = None if path is None else str(path).strip() or None
        return replace(self, default_cwd=cwd)

    def env(self, **values: Any) -> "RecipeSessionRef":
        """Return a new session ref with merged default environment values."""
        merged = dict(self.default_env or {})
        for key, value in values.items():
            merged[str(key)] = "" if value is None else str(value)
        return replace(self, default_env=merged)

    def _session_call(
        self,
        *,
        id: Optional[str] = None,
        depends_on: Optional[Iterable[str]] = None,
        step_options: Optional[Dict[str, Any]] = None,
        after: Any = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> tuple[Optional[str], Optional[list[str]], Optional[Dict[str, Any]]]:
        payload = dict(extra or {})
        if after is not None and "after" not in payload:
            payload["after"] = after
        params, authoring = split_step_call(payload)
        if params:
            unknown = ", ".join(sorted(params))
            raise PythonRecipeError(f"unsupported session options: {unknown}")

        resolved_id = id if id is not None else authoring.get("id")
        merged_depends = self._merge_depends(
            [*(depends_on or []), *(authoring.get("depends_on") or [])]
        )
        linear_seed = self.recipe.current_linear_seed_dependencies()
        if linear_seed:
            merged_depends = self._merge_depends([*merged_depends, *linear_seed])
        merged_options = dict(step_options or {})
        merged_options.update(authoring.get("step_options") or {})
        return (
            resolved_id,
            merged_depends or None,
            merged_options or None,
        )

    def _context_depends(self, depends_on: Optional[Iterable[str]] = None) -> list[str]:
        merged_depends = self._merge_depends(depends_on)
        linear_seed = self.recipe.current_linear_seed_dependencies()
        if linear_seed:
            merged_depends = self._merge_depends([*merged_depends, *linear_seed])
        return merged_depends

    def __call__(self, command: str, **kwargs: Any) -> str:
        """Run one foreground command in this session."""
        return self.run(command, **kwargs)

    def run(
        self,
        command: Any,
        *,
        timeout: Any = 0,
        background: bool = False,
        stdout: Any = None,
        cwd: Optional[str] = None,
        env: Optional[Dict[str, Any]] = None,
        id: Optional[str] = None,
        depends_on: Optional[Iterable[str]] = None,
        step_options: Optional[Dict[str, Any]] = None,
        after: Any = None,
        **kwargs: Any,
    ) -> str:
        """Run one command in this session."""
        resolved_id, merged_depends, merged_options = self._session_call(
            id=id,
            depends_on=depends_on,
            step_options=step_options,
            after=after,
            extra=kwargs,
        )
        return self.recipe.session_run(
            self.name,
            command,
            timeout=timeout,
            background=background,
            stdout=stdout,
            cwd=cwd or self.default_cwd,
            env={**dict(self.default_env or {}), **dict(env or {})} if (self.default_env or env) else None,
            id=resolved_id,
            depends_on=merged_depends,
            step_options=merged_options,
        )

    def bg(self, command: str, **kwargs: Any) -> str:
        """Compact alias for a background command."""
        return self.run(command, background=True, **kwargs)

    def script(
        self,
        body: str,
        *,
        strict: bool = True,
        background: bool = False,
        timeout: Any = 0,
        cwd: Optional[str] = None,
        env: Optional[Dict[str, Any]] = None,
        id: Optional[str] = None,
        depends_on: Optional[Iterable[str]] = None,
        step_options: Optional[Dict[str, Any]] = None,
        after: Any = None,
        **kwargs: Any,
    ) -> str:
        """Run a multiline shell script through bash -lc."""
        script_body = dedent(str(body)).strip("\n")
        if strict:
            script_body = f"set -euo pipefail\n{script_body}" if script_body else "set -euo pipefail"
        command = f"bash -lc {shlex.quote(script_body)}"
        return self.run(
            command,
            timeout=timeout,
            background=background,
            cwd=cwd,
            env=env,
            id=id,
            depends_on=depends_on,
            step_options=step_options,
            after=after,
            **kwargs,
        )

    def sh(self, body: str, **kwargs: Any) -> str:
        """Compact alias for :meth:`script`."""
        return self.script(body, **kwargs)

    def copy_to(
        self,
        source: Any,
        destination: Any,
        *,
        id: Optional[str] = None,
        depends_on: Optional[Iterable[str]] = None,
        step_options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Copy a local/storage source to this session host."""
        return self.recipe.copy(
            self.recipe.resolve_endpoint(source),
            self.remote_path(destination),
            id=id,
            depends_on=self._context_depends(depends_on),
            step_options=step_options,
        )

    def copy_from(
        self,
        source: Any,
        destination: Any,
        *,
        id: Optional[str] = None,
        depends_on: Optional[Iterable[str]] = None,
        step_options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Copy from this session host to a local/storage destination."""
        return self.recipe.copy(
            self.remote_path(source),
            self.recipe.resolve_endpoint(destination),
            id=id,
            depends_on=self._context_depends(depends_on),
            step_options=step_options,
        )

    def sync_to(
        self,
        source: Any,
        destination: Any,
        *,
        id: Optional[str] = None,
        depends_on: Optional[Iterable[str]] = None,
        step_options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Sync a local/storage source to this session host."""
        return self.recipe.sync(
            self.recipe.resolve_endpoint(source),
            self.remote_path(destination),
            id=id,
            depends_on=self._context_depends(depends_on),
            step_options=step_options,
        )

    def sync_from(
        self,
        source: Any,
        destination: Any,
        *,
        id: Optional[str] = None,
        depends_on: Optional[Iterable[str]] = None,
        step_options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Sync from this session host to a local/storage destination."""
        return self.recipe.sync(
            self.remote_path(source),
            self.recipe.resolve_endpoint(destination),
            id=id,
            depends_on=self._context_depends(depends_on),
            step_options=step_options,
        )

    def move_to(
        self,
        source: Any,
        destination: Any,
        *,
        id: Optional[str] = None,
        depends_on: Optional[Iterable[str]] = None,
        step_options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Move a local/storage source to this session host."""
        return self.recipe.move(
            self.recipe.resolve_endpoint(source),
            self.remote_path(destination),
            id=id,
            depends_on=self._context_depends(depends_on),
            step_options=step_options,
        )

    def move_from(
        self,
        source: Any,
        destination: Any,
        *,
        id: Optional[str] = None,
        depends_on: Optional[Iterable[str]] = None,
        step_options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Move from this session host to a local/storage destination."""
        return self.recipe.move(
            self.remote_path(source),
            self.recipe.resolve_endpoint(destination),
            id=id,
            depends_on=self._context_depends(depends_on),
            step_options=step_options,
        )

    def upload(self, source: Any, destination: Any, **kwargs: Any) -> str:
        """Alias for :meth:`copy_to`."""
        return self.copy_to(source, destination, **kwargs)

    def download(self, source: Any, destination: Any, **kwargs: Any) -> str:
        """Alias for :meth:`copy_from`."""
        return self.copy_from(source, destination, **kwargs)

    def install_uv(
        self,
        *,
        force: bool = False,
        id: Optional[str] = None,
        depends_on: Optional[Iterable[str]] = None,
        step_options: Optional[Dict[str, Any]] = None,
        after: Any = None,
        **kwargs: Any,
    ) -> str:
        """Install uv in this tmux session using the official Astral install script."""
        return self.run(
            official_uv_install_command(force=force),
            id=id,
            depends_on=depends_on,
            step_options=step_options,
            after=after,
            **kwargs,
        )

    def capture_pane(
        self,
        *,
        target: str,
        lines: int = 400,
        output: Any,
        id: Optional[str] = None,
        depends_on: Optional[Iterable[str]] = None,
        step_options: Optional[Dict[str, Any]] = None,
        after: Any = None,
        **kwargs: Any,
    ) -> str:
        """Capture one tmux pane into a file on the session host."""
        command = [
            "tmux",
            "capture-pane",
            "-pt",
            str(target),
            "-S",
            f"-{max(0, int(lines))}",
        ]
        return self.run(
            command,
            stdout=output,
            id=id,
            depends_on=depends_on,
            step_options=step_options,
            after=after,
            **kwargs,
        )

    def wait(
        self,
        pattern: Optional[str] = None,
        *,
        file: Optional[str] = None,
        port: Optional[int] = None,
        idle: bool = False,
        timeout: Any = "5m",
        id: Optional[str] = None,
        depends_on: Optional[Iterable[str]] = None,
        step_options: Optional[Dict[str, Any]] = None,
        after: Any = None,
        **kwargs: Any,
    ) -> str:
        """Wait on this session using tmux-session semantics."""
        resolved_id, merged_depends, merged_options = self._session_call(
            id=id,
            depends_on=depends_on,
            step_options=step_options,
            after=after,
            extra=kwargs,
        )
        return self.recipe.session_wait(
            self.name,
            pattern=pattern,
            file=file,
            port=port,
            idle=idle,
            timeout=timeout,
            id=resolved_id,
            depends_on=merged_depends,
            step_options=merged_options,
        )

    def wait_idle(
        self,
        *,
        timeout: Any = "5m",
        id: Optional[str] = None,
        depends_on: Optional[Iterable[str]] = None,
        step_options: Optional[Dict[str, Any]] = None,
        after: Any = None,
        **kwargs: Any,
    ) -> str:
        """Wait until the session pane becomes idle."""
        return self.wait(
            idle=True,
            timeout=timeout,
            id=id,
            depends_on=depends_on,
            step_options=step_options,
            after=after,
            **kwargs,
        )

    def idle(self, **kwargs: Any) -> str:
        """Compact alias for idle waits."""
        return self.wait_idle(**kwargs)

    def file(self, path: str, **kwargs: Any) -> str:
        """Compact alias for file waits."""
        return self.wait(file=path, **kwargs)

    def port(self, value: int, **kwargs: Any) -> str:
        """Compact alias for port waits."""
        return self.wait(port=value, **kwargs)

    def close(
        self,
        *,
        id: Optional[str] = None,
        depends_on: Optional[Iterable[str]] = None,
        step_options: Optional[Dict[str, Any]] = None,
        after: Any = None,
        **kwargs: Any,
    ) -> str:
        """Close this tmux session/window."""
        resolved_id, merged_depends, merged_options = self._session_call(
            id=id,
            depends_on=depends_on,
            step_options=step_options,
            after=after,
            extra=kwargs,
        )
        return self.recipe.tmux_close(
            self.name,
            id=resolved_id,
            depends_on=merged_depends,
            step_options=merged_options,
        )


class RecipeSessionMixin:
    """Helpers that create tmux-session execute/wait steps."""

    def _tmux_ref(
        self,
        name: str,
        *,
        host: Any = None,
        cwd: Optional[str] = None,
        env: Optional[Dict[str, Any]] = None,
        open_step_id: Optional[str] = None,
        id: Optional[str] = None,
        depends_on: Optional[Iterable[str]] = None,
        close: bool = False,
        close_step_options: Optional[Dict[str, Any]] = None,
    ) -> RecipeSessionRef:
        """Bind a proxy to an existing tmux name or open one on demand."""
        if depends_on is None and not self._linear_contexts and self.steps:
            depends_on = self.last()
        session_name = self._clean_session(name)
        remembered = self.lookup_session(session_name) or {}
        if host is not None:
            resolved_host = self.resolve_host(host)
            remembered_host = str(remembered.get("host_ref") or "").strip()
            if not remembered or remembered_host != resolved_host:
                return self.tmux_session(
                    resolved_host,
                    as_=name,
                    cwd=cwd,
                    env=env,
                    id=id,
                    depends_on=depends_on,
                    close=close,
                    close_step_options=close_step_options,
                )
        remembered_open = remembered.get("open_step_id")
        remembered_host = remembered.get("host_ref")
        remembered_cwd = remembered.get("cwd")
        remembered_env = dict(remembered.get("env") or {})
        if open_step_id is None:
            open_step_id = remembered_open
        normalized_depends = normalize_after(depends_on) or []
        merged = []
        seen = set()
        for item in [open_step_id, *normalized_depends]:
            dep = str(item).strip() if item is not None else ""
            if not dep or dep in seen:
                continue
            seen.add(dep)
            merged.append(dep)
        return RecipeSessionRef(
            recipe=self,
            name=session_name,
            open_step_id=open_step_id,
            host_ref=remembered_host,
            default_depends_on=tuple(merged),
            default_cwd=remembered_cwd if cwd is None else (str(cwd).strip() or None),
            default_env=({**remembered_env, **dict(env or {})} if (remembered_env or env) else {}),
            close_on_exit=bool(close),
            close_step_options=close_step_options,
        )

    def tmux_session(
        self,
        host: str,
        *,
        as_: Optional[str] = None,
        cwd: Optional[str] = None,
        env: Optional[Dict[str, Any]] = None,
        id: Optional[str] = None,
        depends_on: Optional[Iterable[str]] = None,
        step_options: Optional[Dict[str, Any]] = None,
        close: bool = False,
        close_step_options: Optional[Dict[str, Any]] = None,
    ) -> RecipeSessionRef:
        """Open a tmux session and return a bound proxy for later steps."""
        session_name = self._clean_session(as_ or "main")
        open_step_id = self.tmux_open(
            host,
            as_=session_name,
            id=id,
            depends_on=depends_on,
            step_options=step_options,
        )
        ref = self._tmux_ref(
            session_name,
            cwd=cwd,
            env=env,
            open_step_id=open_step_id,
            depends_on=[],
            close=close,
            close_step_options=close_step_options,
        )
        ref = replace(ref, host_ref=str(host).strip() or None)
        self.remember_session(
            session_name,
            open_step_id=open_step_id,
            host_ref=ref.host_ref,
            cwd=ref.default_cwd,
            env=ref.default_env,
        )
        return ref

    def _timeout_text(self, timeout: Any) -> str:
        if timeout is None:
            return ""
        if isinstance(timeout, str):
            return timeout.strip()
        if isinstance(timeout, bool):
            return str(int(timeout))
        if isinstance(timeout, (int, float)):
            return str(int(timeout))
        return str(timeout).strip()

    def session_run(
        self,
        session: str,
        command: Any,
        *,
        timeout: Any = 0,
        background: bool = False,
        stdout: Any = None,
        cwd: Optional[str] = None,
        env: Optional[Dict[str, Any]] = None,
        id: Optional[str] = None,
        depends_on: Optional[Iterable[str]] = None,
        step_options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Build one execute step against a tmux session name."""
        session_name = self._clean_session(session)
        timeout_secs = self._normalize_timeout(timeout) if self._timeout_text(timeout) else 0

        if isinstance(command, (list, tuple)):
            command_text = shlex.join(str(item) for item in command)
        else:
            command_text = str(command)
        env_parts = []
        for key, value in (env or {}).items():
            key_text = str(key).strip()
            if not key_text:
                continue
            env_parts.append(f"export {key_text}={shlex.quote('' if value is None else str(value))}")
        cwd_text = None if cwd is None else str(cwd).strip() or None
        if cwd_text or env_parts:
            shell_lines = [*env_parts]
            if cwd_text:
                shell_lines.append(f"cd {shlex.quote(cwd_text)}")
            shell_lines.append(command_text)
            command_text = f"bash -lc {shlex.quote('; '.join(shell_lines))}"
        if stdout is not None:
            command_text = f"{command_text} > {shlex.quote(self.resolve_endpoint(stdout))}"

        raw = f"@{session_name}"
        if timeout_secs > 0:
            raw += f" timeout={self._timeout_text(timeout) or timeout_secs}"
        raw += f" > {command_text}"
        if self._normalize_bool(background, default=False):
            raw += " &"

        step = RecipeStepModel(
            type=StepType.EXECUTE,
            line_num=0,
            raw=raw,
            host=session_name,
            commands=command_text,
            background=self._normalize_bool(background, default=False),
            timeout=max(0, int(timeout_secs)),
        )
        return self._add_step(
            step,
            id=id,
            depends_on=depends_on,
            step_options=step_options,
        )

    def session_wait(
        self,
        session: str,
        *,
        pattern: Optional[str] = None,
        file: Optional[str] = None,
        port: Optional[int] = None,
        idle: bool = False,
        timeout: Any = "5m",
        id: Optional[str] = None,
        depends_on: Optional[Iterable[str]] = None,
        step_options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Build one wait step against a tmux session name."""
        session_name = self._clean_session(session)
        selected = [
            pattern is not None,
            file is not None,
            port is not None,
            self._normalize_bool(idle, default=False),
        ]
        if sum(1 for item in selected if item) > 1:
            raise PythonRecipeError("session_wait accepts only one of pattern/file/port/idle")

        if not any(selected):
            idle = True

        timeout_secs = self._normalize_timeout(timeout)
        raw = f"wait @{session_name}"
        wait_pattern = ""
        condition = ""

        if pattern is not None:
            wait_pattern = str(pattern)
            raw += f" {json.dumps(wait_pattern)}"
        elif file is not None:
            condition = f"file:{file}"
            raw += f" file={file}"
        elif port is not None:
            condition = f"port:{int(port)}"
            raw += f" port={int(port)}"
        else:
            condition = "idle"
            raw += " idle"

        timeout_text = self._timeout_text(timeout)
        if timeout_text:
            raw += f" timeout={timeout_text}"

        step = RecipeStepModel(
            type=StepType.WAIT,
            line_num=0,
            raw=raw,
            target=session_name,
            pattern=wait_pattern,
            condition=condition,
            timeout=max(0, int(timeout_secs)),
        )
        return self._add_step(
            step,
            id=id,
            depends_on=depends_on,
            step_options=step_options,
        )
