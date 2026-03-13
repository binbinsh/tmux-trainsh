"""Session-oriented helpers for Python recipes."""

from __future__ import annotations

import json
import shlex
from dataclasses import dataclass, field, replace
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
    default_depends_on: tuple[str, ...] = field(default_factory=tuple)

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

    def after(self, *dependencies: Any) -> "RecipeSessionRef":
        """Return a new session ref with extra default dependencies."""
        normalized: list[str] = []
        for item in dependencies:
            normalized.extend(normalize_after(item) or [])
        if self.open_step_id and normalized:
            self.recipe.link_step_dependencies(self.open_step_id, normalized)
        return replace(
            self,
            default_depends_on=tuple(self._merge_depends(normalized)),
        )

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
        linear_last = self.recipe.current_linear_dependency()
        if linear_last is not None:
            merged_depends = self._merge_depends([*merged_depends, linear_last])
        merged_options = dict(step_options or {})
        merged_options.update(authoring.get("step_options") or {})
        return (
            resolved_id,
            merged_depends or None,
            merged_options or None,
        )

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
            id=resolved_id,
            depends_on=merged_depends,
            step_options=merged_options,
        )

    def bg(self, command: str, **kwargs: Any) -> str:
        """Compact alias for a background command."""
        return self.run(command, background=True, **kwargs)

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

    def session(
        self,
        name: str,
        *,
        host: Any = None,
        open_step_id: Optional[str] = None,
        id: Optional[str] = None,
        depends_on: Optional[Iterable[str]] = None,
    ) -> RecipeSessionRef:
        """Bind a proxy to an existing session/window name or open one on demand."""
        if host is not None:
            return self.tmux_session(
                self.resolve_host(host),
                as_=name,
                id=id,
                depends_on=depends_on,
            )
        session_name = self._clean_session(name)
        merged = []
        seen = set()
        for item in [open_step_id, *(depends_on or [])]:
            dep = str(item).strip() if item is not None else ""
            if not dep or dep in seen:
                continue
            seen.add(dep)
            merged.append(dep)
        return RecipeSessionRef(
            recipe=self,
            name=session_name,
            open_step_id=open_step_id,
            default_depends_on=tuple(merged),
        )

    def tmux_session(
        self,
        host: str,
        *,
        as_: Optional[str] = None,
        id: Optional[str] = None,
        depends_on: Optional[Iterable[str]] = None,
        step_options: Optional[Dict[str, Any]] = None,
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
        return self.session(session_name, open_step_id=open_step_id)

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
