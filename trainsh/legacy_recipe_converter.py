"""Convert legacy `.recipe` DSL files into the current Python recipe DSL."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Optional, Tuple


CONTROL_COMMANDS = {
    "tmux.open",
    "tmux.close",
    "tmux.config",
    "vast.pick",
    "vast.start",
    "vast.stop",
    "vast.wait",
    "vast.cost",
    "notify",
    "sleep",
}


class LegacyRecipeConversionError(ValueError):
    """Raised when a legacy `.recipe` file cannot be converted safely."""


@dataclass(frozen=True)
class LegacyExecute:
    session: str
    command: str
    background: bool = False
    timeout: Optional[str] = None


@dataclass(frozen=True)
class LegacyWait:
    session: str
    pattern: Optional[str] = None
    file_path: Optional[str] = None
    port: Optional[int] = None
    idle: bool = False
    timeout: Optional[str] = None


@dataclass(frozen=True)
class LegacyTransfer:
    source: str
    destination: str


class LegacyRecipeConverter:
    """Line-oriented converter for the removed `.recipe` DSL."""

    def __init__(self, recipe_name: str):
        self.recipe_name = recipe_name
        self._session_vars: Dict[str, str] = {}
        self._used_names: set[str] = set()
        self._step_index = 0
        self._last_step_ref: Optional[str] = None
        self._lines: List[str] = []

    def convert(self, content: str) -> str:
        self._session_vars.clear()
        self._used_names.clear()
        self._step_index = 0
        self._last_step_ref = None
        self._lines = [
            "from trainsh.pyrecipe import *",
            "",
            f"recipe({self._py_string(self.recipe_name)})",
        ]

        saw_body = False
        for _line_num, line in self._iter_lines(content):
            stripped = line.strip()
            if not stripped:
                if self._lines and self._lines[-1] != "":
                    self._lines.append("")
                continue
            if stripped.startswith("#"):
                self._lines.append(line.rstrip())
                continue

            if not saw_body and self._lines[-1] != "":
                self._lines.append("")
            saw_body = True
            self._convert_line(line.rstrip("\n"))

        while self._lines and self._lines[-1] == "":
            self._lines.pop()
        return "\n".join(self._lines) + "\n"

    def _convert_line(self, line: str) -> None:
        stripped = line.strip()
        if stripped.startswith("var "):
            name, value = self._parse_assignment(stripped, "var")
            self._lines.append(f"var({self._py_string(name)}, {self._py_string(value)})")
            return
        if stripped.startswith("host "):
            name, value = self._parse_assignment(stripped, "host")
            self._lines.append(f"host({self._py_string(name)}, {self._py_string(value)})")
            return
        if stripped.startswith("storage "):
            name, value = self._parse_assignment(stripped, "storage")
            self._lines.append(f"storage({self._py_string(name)}, {self._py_string(value)})")
            return
        if stripped.startswith("wait "):
            self._convert_wait(self._parse_wait(stripped))
            return
        if stripped.startswith("@") and " > " in stripped:
            self._convert_execute(self._parse_execute(line))
            return
        if " -> " in stripped:
            source, destination = [item.strip() for item in stripped.split(" -> ", 1)]
            self._convert_transfer(LegacyTransfer(source=source, destination=destination))
            return

        parts = self._split_args(stripped)
        if not parts:
            return
        command = parts[0]
        if command not in CONTROL_COMMANDS:
            raise LegacyRecipeConversionError(f"unsupported legacy syntax: {line}")
        self._convert_control(command, parts[1:])

    def _convert_execute(self, step: LegacyExecute) -> None:
        session_var = self._session_var(step.session)
        step_name = self._next_step_name("step")
        call = "bg" if step.background else None
        kwargs = self._step_kwargs(timeout=step.timeout)
        if call is None:
            expr = f"{session_var}({self._py_string(step.command)}{kwargs})"
        else:
            expr = f"{session_var}.{call}({self._py_string(step.command)}{kwargs})"
        self._lines.append(f"{step_name} = {expr}")
        self._last_step_ref = step_name

    def _convert_wait(self, step: LegacyWait) -> None:
        session_var = self._session_var(step.session)
        step_name = self._next_step_name("wait")
        kwargs = self._step_kwargs(timeout=step.timeout)
        if step.pattern is not None:
            expr = f"{session_var}.wait({self._py_string(step.pattern)}{kwargs})"
        elif step.file_path is not None:
            expr = f"{session_var}.file({self._py_string(step.file_path)}{kwargs})"
        elif step.port is not None:
            expr = f"{session_var}.port({step.port}{kwargs})"
        elif step.idle:
            expr = f"{session_var}.idle({kwargs[2:]})" if kwargs else f"{session_var}.idle()"
        else:
            raise LegacyRecipeConversionError(f"unsupported wait form for @{step.session}")
        self._lines.append(f"{step_name} = {expr}")
        self._last_step_ref = step_name

    def _convert_transfer(self, step: LegacyTransfer) -> None:
        step_name = self._next_step_name("transfer")
        kwargs = self._step_kwargs()
        expr = f"transfer({self._py_string(step.source)}, {self._py_string(step.destination)}{kwargs})"
        self._lines.append(f"{step_name} = {expr}")
        self._last_step_ref = step_name

    def _convert_control(self, command: str, args: List[str]) -> None:
        if command == "tmux.open":
            self._convert_tmux_open(args)
            return
        if command == "tmux.close":
            self._convert_tmux_close(args)
            return
        if command == "tmux.config":
            host_name = self._host_ref(args[0]) if args else "local"
            step_name = self._next_step_name("tmux_config")
            self._lines.append(f"{step_name} = tmux_config({self._py_string(host_name)}{self._step_kwargs()})")
            self._last_step_ref = step_name
            return
        if command == "notify":
            message = " ".join(args).strip()
            step_name = self._next_step_name("notice")
            self._lines.append(f"{step_name} = notice({self._py_string(message)}{self._step_kwargs()})")
            self._last_step_ref = step_name
            return
        if command == "sleep":
            duration = args[0] if args else "0s"
            step_name = self._next_step_name("sleep")
            self._lines.append(f"{step_name} = sleep({self._py_string(duration)}{self._step_kwargs()})")
            self._last_step_ref = step_name
            return
        if command.startswith("vast."):
            self._convert_vast(command, args)
            return
        raise LegacyRecipeConversionError(f"unsupported control command: {command}")

    def _convert_tmux_open(self, args: List[str]) -> None:
        if len(args) < 3 or args[1] != "as":
            raise LegacyRecipeConversionError("tmux.open expects '@host as session'")
        host_name = self._host_ref(args[0])
        session_name = self._session_name(args[2])
        session_var = self._register_session_var(session_name)
        kwargs = self._step_kwargs()
        expr = f"session({self._py_string(session_name)}, on={self._py_string(host_name)}{kwargs})"
        self._lines.append(f"{session_var} = {expr}")
        self._last_step_ref = session_var

    def _convert_tmux_close(self, args: List[str]) -> None:
        if not args:
            raise LegacyRecipeConversionError("tmux.close expects a session reference")
        session_name = self._session_name(args[0])
        session_var = self._session_var(session_name)
        step_name = self._next_step_name("close")
        kwargs = self._step_kwargs()
        expr = f"{session_var}.close({kwargs[2:]})" if kwargs else f"{session_var}.close()"
        self._lines.append(f"{step_name} = {expr}")
        self._last_step_ref = step_name

    def _convert_vast(self, command: str, args: List[str]) -> None:
        op = command.split(".", 1)[1]
        helper = f"vast_{op}"
        positionals: List[str] = []
        keyword_parts: List[str] = []
        for token in args:
            if "=" in token:
                key, value = token.split("=", 1)
                if key == "host":
                    keyword_parts.append(f"host={self._py_string(self._host_ref(value))}")
                else:
                    keyword_parts.append(f"{key}={self._py_value(value)}")
                continue
            if token.startswith("@"):
                if op == "pick":
                    keyword_parts.append(f"host={self._py_string(self._host_ref(token))}")
                else:
                    keyword_parts.append(f"instance_id={self._py_string(self._host_ref(token))}")
                continue
            positionals.append(self._py_value(token))

        joined = ", ".join(positionals + keyword_parts)
        kwargs = self._step_kwargs()
        if joined and kwargs:
            expr = f"{helper}({joined}{kwargs})"
        elif joined:
            expr = f"{helper}({joined})"
        else:
            expr = f"{helper}({kwargs[2:]})" if kwargs else f"{helper}()"
        step_name = self._next_step_name(op)
        self._lines.append(f"{step_name} = {expr}")
        self._last_step_ref = step_name

    def _step_kwargs(self, *, timeout: Optional[str] = None) -> str:
        parts: List[str] = []
        if timeout:
            parts.append(f"timeout={self._py_string(timeout)}")
        if self._last_step_ref is not None:
            parts.append(f"after={self._last_step_ref}")
        if not parts:
            return ""
        return ", " + ", ".join(parts)

    def _session_var(self, session_name: str) -> str:
        try:
            return self._session_vars[session_name]
        except KeyError as exc:
            raise LegacyRecipeConversionError(f"session @{session_name} used before tmux.open") from exc

    def _register_session_var(self, session_name: str) -> str:
        base = self._safe_name(session_name)
        name = self._unique_name(base)
        self._session_vars[session_name] = name
        return name

    def _next_step_name(self, prefix: str) -> str:
        self._step_index += 1
        return self._unique_name(f"{self._safe_name(prefix)}_{self._step_index:03d}")

    def _unique_name(self, base: str) -> str:
        candidate = base or "step"
        index = 1
        while candidate in self._used_names:
            index += 1
            candidate = f"{base}_{index}"
        self._used_names.add(candidate)
        return candidate

    @staticmethod
    def _safe_name(text: str) -> str:
        name = re.sub(r"[^A-Za-z0-9_]+", "_", str(text).strip()).strip("_").lower()
        if not name:
            return "step"
        if name[0].isdigit():
            name = f"step_{name}"
        return name

    @staticmethod
    def _host_ref(text: str) -> str:
        return str(text).strip().lstrip("@")

    @staticmethod
    def _session_name(text: str) -> str:
        return str(text).strip().lstrip("@")

    @staticmethod
    def _parse_assignment(line: str, kind: str) -> tuple[str, str]:
        matched = re.match(rf"^{kind}\s+(\w+)\s*=\s*(.+)$", line)
        if not matched:
            raise LegacyRecipeConversionError(f"invalid {kind} definition: {line}")
        return matched.group(1), matched.group(2).strip()

    def _parse_execute(self, line: str) -> LegacyExecute:
        host_part, command = line.split(" > ", 1)
        host_tokens = host_part.strip().split()
        session = self._session_name(host_tokens[0])
        timeout = None
        for token in host_tokens[1:]:
            if token.startswith("timeout="):
                timeout = token.split("=", 1)[1]
        command_text = command.rstrip()
        background = command_text.endswith("&")
        if background:
            command_text = command_text[:-1].rstrip()
        return LegacyExecute(
            session=session,
            command=command_text,
            background=background,
            timeout=timeout,
        )

    def _parse_wait(self, line: str) -> LegacyWait:
        content = line[5:].strip()
        matched = re.match(r"^@(\w+)\s*(.*)$", content)
        if not matched:
            raise LegacyRecipeConversionError("wait requires a @session target")
        session = matched.group(1)
        tail = matched.group(2).strip()

        pattern = None
        file_path = None
        port = None
        idle = False
        timeout = None

        pattern_match = re.search(r'"([^"]+)"', tail)
        if pattern_match:
            pattern = pattern_match.group(1)
            tail = tail.replace(pattern_match.group(0), "").strip()

        for key, value in re.findall(r"(\w+)=([^\s]+)", tail):
            if key == "timeout":
                timeout = value
            elif key == "file":
                file_path = value
            elif key == "port":
                port = int(value)
            elif key == "idle" and value.lower() == "true":
                idle = True
        if "idle" in tail and "idle=" not in tail:
            idle = True

        return LegacyWait(
            session=session,
            pattern=pattern,
            file_path=file_path,
            port=port,
            idle=idle,
            timeout=timeout,
        )

    @staticmethod
    def _split_args(text: str) -> List[str]:
        args: List[str] = []
        current = ""
        in_quotes = False
        quote_char = ""
        for char in text:
            if char in {'"', "'"}:
                if not in_quotes:
                    in_quotes = True
                    quote_char = char
                elif char == quote_char:
                    in_quotes = False
                    quote_char = ""
                else:
                    current += char
            elif char == " " and not in_quotes:
                if current:
                    args.append(current)
                    current = ""
            else:
                current += char
        if current:
            args.append(current)
        return args

    @staticmethod
    def _iter_lines(content: str) -> Iterator[Tuple[int, str]]:
        lines = content.splitlines()
        index = 0
        while index < len(lines):
            line = lines[index]
            line_num = index + 1
            stripped = line.strip()

            if stripped.startswith("@") and " > " in stripped:
                combined = line
                command = line.split(" > ", 1)[1]
                heredoc = LegacyRecipeConverter._detect_heredoc_delim(command)
                if heredoc:
                    index += 1
                    found = False
                    while index < len(lines):
                        combined += "\n" + lines[index]
                        if lines[index].strip() == heredoc:
                            found = True
                            break
                        index += 1
                    if not found:
                        raise LegacyRecipeConversionError(f"unterminated heredoc {heredoc!r}")
                    yield line_num, combined
                    index += 1
                    continue

                while combined.rstrip().endswith("\\"):
                    if index + 1 >= len(lines):
                        raise LegacyRecipeConversionError("line continuation at end of file")
                    index += 1
                    combined += "\n" + lines[index]

                yield line_num, combined
                index += 1
                continue

            yield line_num, line
            index += 1

    @staticmethod
    def _detect_heredoc_delim(command: str) -> Optional[str]:
        matched = re.search(r"<<-?\s*(['\"]?)([A-Za-z0-9_]+)\1", command)
        return matched.group(2) if matched else None

    @staticmethod
    def _py_value(text: str) -> str:
        value = text.strip()
        lowered = value.lower()
        if lowered in {"true", "false"}:
            return "True" if lowered == "true" else "False"
        if re.fullmatch(r"-?\d+", value):
            return value
        if re.fullmatch(r"-?\d+\.\d+", value):
            return value
        return LegacyRecipeConverter._py_string(value)

    @staticmethod
    def _py_string(text: str) -> str:
        value = text.replace("\r\n", "\n")
        if "\n" not in value:
            return json.dumps(value)
        escaped = value.replace('"""', '\\"\\"\\"')
        return f'"""{escaped}"""'


def convert_legacy_recipe_text(content: str, *, recipe_name: str) -> str:
    """Convert one legacy `.recipe` text blob to the current Python DSL."""
    return LegacyRecipeConverter(recipe_name).convert(content)


def convert_legacy_recipe_file(
    source: Path | str,
    *,
    output: Optional[Path | str] = None,
    force: bool = False,
) -> Path:
    """Convert one legacy `.recipe` file and write the Python result."""
    source_path = Path(source).expanduser().resolve()
    if source_path.suffix != ".recipe":
        raise LegacyRecipeConversionError(f"expected a .recipe file: {source_path}")
    if not source_path.exists():
        raise FileNotFoundError(source_path)

    output_path = Path(output).expanduser().resolve() if output is not None else source_path.with_suffix(".py")
    if output_path.exists() and not force:
        raise LegacyRecipeConversionError(f"output already exists: {output_path}")

    converted = convert_legacy_recipe_text(
        source_path.read_text(encoding="utf-8"),
        recipe_name=source_path.stem,
    )
    output_path.write_text(converted, encoding="utf-8")
    return output_path


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", help="Legacy .recipe file or a directory containing .recipe files.")
    parser.add_argument(
        "--output",
        help="Output file or output directory. Defaults to writing sibling .py files.",
    )
    parser.add_argument("--force", action="store_true", help="Overwrite existing output files.")
    args = parser.parse_args(list(argv) if argv is not None else None)

    source_path = Path(args.source).expanduser().resolve()
    output_arg = Path(args.output).expanduser().resolve() if args.output else None

    if source_path.is_dir():
        output_dir = output_arg or source_path
        output_dir.mkdir(parents=True, exist_ok=True)
        converted = 0
        for recipe_path in sorted(source_path.rglob("*.recipe")):
            relative = recipe_path.relative_to(source_path)
            target = output_dir / relative.with_suffix(".py")
            target.parent.mkdir(parents=True, exist_ok=True)
            convert_legacy_recipe_file(recipe_path, output=target, force=args.force)
            print(f"{recipe_path} -> {target}")
            converted += 1
        if converted == 0:
            raise LegacyRecipeConversionError(f"no .recipe files found under {source_path}")
        return 0

    target = output_arg if output_arg is not None else source_path.with_suffix(".py")
    written = convert_legacy_recipe_file(source_path, output=target, force=args.force)
    print(written)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
