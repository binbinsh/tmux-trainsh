# tmux-trainsh DSL parser
# Parses .recipe files into Recipe objects

import re
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass, field
from enum import Enum


class StepType(Enum):
    """Type of DSL step."""
    CONTROL = "control"      # > command
    EXECUTE = "execute"      # host: command
    TRANSFER = "transfer"    # path -> path
    WAIT = "wait"            # ? condition


@dataclass
class DSLStep:
    """Parsed DSL step."""
    type: StepType
    line_num: int
    raw: str

    # For CONTROL steps
    command: str = ""
    args: List[str] = field(default_factory=list)

    # For EXECUTE steps
    host: str = ""
    commands: str = ""
    background: bool = False

    # For TRANSFER steps
    source: str = ""
    dest: str = ""

    # For WAIT steps
    target: str = ""
    pattern: str = ""
    condition: str = ""
    timeout: int = 0


@dataclass
class DSLRecipe:
    """Parsed DSL recipe."""
    name: str = ""
    variables: Dict[str, str] = field(default_factory=dict)
    hosts: Dict[str, str] = field(default_factory=dict)
    steps: List[DSLStep] = field(default_factory=list)


class DSLParser:
    """
    Parser for .recipe DSL files.

    Syntax:
        ---
        VAR = value
        ---

        @host = reference

        > control.command args
        host: shell command
        source -> dest
        ? host: "pattern" timeout=300
    """

    def __init__(self):
        self.variables: Dict[str, str] = {}
        self.hosts: Dict[str, str] = {"local": "local"}
        self.steps: List[DSLStep] = []
        self.line_num = 0
        self.in_var_block = False

    def parse(self, content: str, name: str = "") -> DSLRecipe:
        """Parse DSL content into a recipe."""
        self.variables = {}
        self.hosts = {"local": "local"}
        self.steps = []
        self.line_num = 0
        self.in_var_block = False

        lines = content.split('\n')

        for i, line in enumerate(lines):
            self.line_num = i + 1
            self._parse_line(line)

        return DSLRecipe(
            name=name,
            variables=self.variables,
            hosts=self.hosts,
            steps=self.steps,
        )

    def parse_file(self, path: str) -> DSLRecipe:
        """Parse a .recipe file."""
        import os
        with open(os.path.expanduser(path), 'r') as f:
            content = f.read()
        name = os.path.basename(path).rsplit('.', 1)[0]
        return self.parse(content, name)

    def _parse_line(self, line: str) -> None:
        """Parse a single line."""
        # Strip and skip empty/comment lines
        stripped = line.strip()
        if not stripped or stripped.startswith('#'):
            return

        # Variable block delimiter
        if stripped == '---':
            self.in_var_block = not self.in_var_block
            return

        # Inside variable block
        if self.in_var_block:
            self._parse_variable(stripped)
            return

        # Host definition: @name = value
        if stripped.startswith('@') and '=' in stripped:
            self._parse_host_def(stripped)
            return

        # Control command: > command
        if stripped.startswith('>'):
            self._parse_control(stripped)
            return

        # Wait/check: ? condition
        if stripped.startswith('?'):
            self._parse_wait(stripped)
            return

        # Transfer: source -> dest or source <- dest
        if ' -> ' in stripped or ' <- ' in stripped:
            self._parse_transfer(stripped)
            return

        # Execute: host: command
        if ':' in stripped and not stripped.startswith('/'):
            # Check if it looks like host:command (not a URL or path)
            parts = stripped.split(':', 1)
            if parts[0].strip() and not parts[0].strip().startswith('http'):
                self._parse_execute(stripped)
                return

        # Unknown line - treat as comment for now
        pass

    def _parse_variable(self, line: str) -> None:
        """Parse variable definition: VAR = value"""
        match = re.match(r'^(\w+)\s*=\s*(.+)$', line)
        if match:
            name, value = match.groups()
            self.variables[name] = value.strip()

    def _parse_host_def(self, line: str) -> None:
        """Parse host definition: @name = value"""
        match = re.match(r'^@(\w+)\s*=\s*(.+)$', line)
        if match:
            name, value = match.groups()
            self.hosts[name] = self._interpolate(value.strip())

    def _parse_control(self, line: str) -> None:
        """Parse control command: > command args"""
        content = line[1:].strip()
        parts = self._split_args(content)

        if not parts:
            return

        command = parts[0]
        args = parts[1:] if len(parts) > 1 else []

        self.steps.append(DSLStep(
            type=StepType.CONTROL,
            line_num=self.line_num,
            raw=line,
            command=command,
            args=args,
        ))

    def _parse_execute(self, line: str) -> None:
        """Parse execute command: host: command"""
        colon_idx = line.index(':')
        host = line[:colon_idx].strip()
        commands = line[colon_idx + 1:].strip()

        # Check for background execution
        background = commands.endswith('&')
        if background:
            commands = commands[:-1].strip()

        # Resolve host reference
        if host.startswith('@'):
            host = host[1:]

        self.steps.append(DSLStep(
            type=StepType.EXECUTE,
            line_num=self.line_num,
            raw=line,
            host=host,
            commands=self._interpolate(commands),
            background=background,
        ))

    def _parse_transfer(self, line: str) -> None:
        """Parse transfer: source -> dest or source <- dest"""
        if ' -> ' in line:
            source, dest = line.split(' -> ', 1)
            source = source.strip()
            dest = dest.strip()
        else:  # ' <- '
            dest, source = line.split(' <- ', 1)
            source = source.strip()
            dest = dest.strip()

        self.steps.append(DSLStep(
            type=StepType.TRANSFER,
            line_num=self.line_num,
            raw=line,
            source=self._interpolate(source),
            dest=self._interpolate(dest),
        ))

    def _parse_wait(self, line: str) -> None:
        """Parse wait condition: ? host: "pattern" timeout=N"""
        content = line[1:].strip()

        target = ""
        pattern = ""
        condition = ""
        timeout = 300  # default 5 minutes

        # Check for host: prefix
        if ':' in content:
            colon_idx = content.index(':')
            target = content[:colon_idx].strip()
            if target.startswith('@'):
                target = target[1:]
            content = content[colon_idx + 1:].strip()

        # Extract quoted pattern
        pattern_match = re.search(r'"([^"]+)"', content)
        if pattern_match:
            pattern = pattern_match.group(1)
            content = content.replace(f'"{pattern}"', '').strip()

        # Extract key=value options
        for opt in re.findall(r'(\w+)=(\S+)', content):
            key, value = opt
            if key == 'timeout':
                timeout = self._parse_duration(value)
            elif key == 'file':
                condition = f"file:{value}"
            elif key == 'port':
                condition = f"port:{value}"

        self.steps.append(DSLStep(
            type=StepType.WAIT,
            line_num=self.line_num,
            raw=line,
            target=target,
            pattern=pattern,
            condition=condition,
            timeout=timeout,
        ))

    def _interpolate(self, text: str) -> str:
        """Interpolate ${VAR} references."""
        def replace_var(match):
            var_name = match.group(1)
            if var_name.startswith('secret:'):
                return match.group(0)  # Keep secret refs as-is
            return self.variables.get(var_name, match.group(0))

        return re.sub(r'\$\{(\w+(?::\w+)?)\}', replace_var, text)

    def _split_args(self, text: str) -> List[str]:
        """Split arguments respecting quotes."""
        args = []
        current = ""
        in_quotes = False
        quote_char = None

        for char in text:
            if char in '"\'':
                if not in_quotes:
                    in_quotes = True
                    quote_char = char
                elif char == quote_char:
                    in_quotes = False
                    quote_char = None
                else:
                    current += char
            elif char == ' ' and not in_quotes:
                if current:
                    args.append(current)
                    current = ""
            else:
                current += char

        if current:
            args.append(current)

        return args

    def _parse_duration(self, value: str) -> int:
        """Parse duration string to seconds: 1h, 30m, 300, etc."""
        value = value.strip().lower()

        if value.endswith('h'):
            return int(value[:-1]) * 3600
        elif value.endswith('m'):
            return int(value[:-1]) * 60
        elif value.endswith('s'):
            return int(value[:-1])
        else:
            return int(value)


def parse_recipe(path: str) -> DSLRecipe:
    """Convenience function to parse a recipe file."""
    parser = DSLParser()
    return parser.parse_file(path)


def parse_recipe_string(content: str, name: str = "") -> DSLRecipe:
    """Convenience function to parse recipe content."""
    parser = DSLParser()
    return parser.parse(content, name)
