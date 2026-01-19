# tmux-trainsh DSL parser
# Parses .recipe files into Recipe objects

import re
from typing import Optional, List, Dict, Set, Iterator, Tuple
from dataclasses import dataclass, field
from enum import Enum


class StepType(Enum):
    """Type of DSL step."""
    CONTROL = "control"      # command args (e.g., vast.pick, tmux.open)
    EXECUTE = "execute"      # @session > command
    TRANSFER = "transfer"    # @src:path -> @dst:path
    WAIT = "wait"            # wait @session condition


# Control commands that are recognized
CONTROL_COMMANDS = {
    "tmux.open", "tmux.close", "tmux.config",
    "vast.pick", "vast.start", "vast.stop", "vast.wait", "vast.cost",
    "notify", "sleep",
}


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
    timeout: int = 0

    # For TRANSFER steps
    source: str = ""
    dest: str = ""

    # For WAIT steps
    target: str = ""
    pattern: str = ""
    condition: str = ""


@dataclass
class DSLRecipe:
    """Parsed DSL recipe."""
    name: str = ""
    variables: Dict[str, str] = field(default_factory=dict)
    hosts: Dict[str, str] = field(default_factory=dict)
    storages: Dict[str, str] = field(default_factory=dict)
    steps: List[DSLStep] = field(default_factory=list)


class DSLParseError(Exception):
    """Error during DSL parsing."""
    def __init__(self, message: str, line_num: int = 0, line: str = ""):
        self.line_num = line_num
        self.line = line
        super().__init__(f"Line {line_num}: {message}")


class DSLParser:
    """
    Parser for .recipe DSL files.

    Syntax:
        # Variables (reference with $NAME or ${NAME})
        var NAME = value

        # Hosts (reference with @NAME)
        host NAME = spec

        # Storage (reference with @NAME)
        storage NAME = spec

        # Control commands
        vast.pick @host options
        tmux.open @host as session
        tmux.close @session
        notify "message"

        # Execute commands
        @session > command
        @session > command &
        @session timeout=2h > command

        # Wait commands
        wait @session "pattern" timeout=2h
        wait @session file=path timeout=1h
        wait @session idle timeout=30m

        # Transfer commands
        @src:path -> @dst:path
        ./local -> @host:remote
    """

    def __init__(self):
        self.variables: Dict[str, str] = {}
        self.hosts: Dict[str, str] = {}
        self.storages: Dict[str, str] = {}
        self.defined_names: Set[str] = set()  # Track all defined names
        self.steps: List[DSLStep] = []
        self.line_num = 0

    def parse(self, content: str, name: str = "") -> DSLRecipe:
        """Parse DSL content into a recipe."""
        self.variables = {}
        self.hosts = {}
        self.storages = {}
        self.defined_names = set()
        self.steps = []
        self.line_num = 0

        for line_num, line in self._iter_lines(content):
            self.line_num = line_num
            self._parse_line(line)

        return DSLRecipe(
            name=name,
            variables=self.variables,
            hosts=self.hosts,
            storages=self.storages,
            steps=self.steps,
        )

    def parse_file(self, path: str) -> DSLRecipe:
        """Parse a .recipe file."""
        import os
        with open(os.path.expanduser(path), 'r') as f:
            content = f.read()
        name = os.path.basename(path).rsplit('.', 1)[0]
        return self.parse(content, name)

    def _iter_lines(self, content: str) -> Iterator[Tuple[int, str]]:
        """Yield logical lines, joining multiline execute commands."""
        lines = content.split('\n')
        i = 0
        while i < len(lines):
            line = lines[i]
            line_num = i + 1
            stripped = line.strip()

            if stripped.startswith('@') and ' > ' in stripped:
                combined = line
                command = line.split(' > ', 1)[1]
                heredoc_delim = self._detect_heredoc_delim(command)
                if heredoc_delim:
                    i += 1
                    found = False
                    while i < len(lines):
                        combined += '\n' + lines[i]
                        if lines[i].strip() == heredoc_delim:
                            found = True
                            break
                        i += 1
                    if not found:
                        raise DSLParseError(
                            f"Unterminated heredoc (expected '{heredoc_delim}')",
                            line_num
                        )
                    yield line_num, combined
                    i += 1
                    continue

                while combined.rstrip().endswith('\\'):
                    if i + 1 >= len(lines):
                        raise DSLParseError("Line continuation at end of file", line_num)
                    i += 1
                    combined += '\n' + lines[i]

                yield line_num, combined
                i += 1
                continue

            yield line_num, line
            i += 1

    def _detect_heredoc_delim(self, command: str) -> Optional[str]:
        """Detect heredoc delimiter in an execute command."""
        match = re.search(r"<<-?\s*(['\"]?)([A-Za-z0-9_]+)\1", command)
        if match:
            return match.group(2)
        return None

    def _check_duplicate_name(self, name: str, kind: str) -> None:
        """Check if a name is already defined."""
        if name in self.defined_names:
            raise DSLParseError(
                f"Duplicate definition: '{name}' is already defined",
                self.line_num
            )
        self.defined_names.add(name)

    def _parse_line(self, line: str) -> None:
        """Parse a single line."""
        # Strip and skip empty/comment lines
        stripped = line.strip()
        if not stripped or stripped.startswith('#'):
            return

        # New syntax: var NAME = value
        if stripped.startswith('var '):
            self._parse_var_def(stripped)
            return

        # New syntax: host NAME = spec
        if stripped.startswith('host '):
            self._parse_host_def(stripped)
            return

        # New syntax: storage NAME = spec
        if stripped.startswith('storage '):
            self._parse_storage_def(stripped)
            return

        # New syntax: wait @session condition
        if stripped.startswith('wait '):
            self._parse_wait(stripped)
            return

        # New syntax: @session > command (execute)
        if ' > ' in stripped and stripped.startswith('@'):
            self._parse_execute(line)
            return

        # Transfer: source -> dest
        if ' -> ' in stripped:
            self._parse_transfer(stripped)
            return

        # Control command: command args (e.g., vast.pick @gpu, tmux.open @host)
        # Check if line starts with a known control command
        first_word = stripped.split()[0] if stripped.split() else ""
        if first_word in CONTROL_COMMANDS:
            self._parse_control(stripped)
            return

        raise DSLParseError(f"Unrecognized DSL syntax: {line}", self.line_num)

    def _parse_var_def(self, line: str) -> None:
        """Parse variable definition: var NAME = value"""
        match = re.match(r'^var\s+(\w+)\s*=\s*(.+)$', line)
        if match:
            name, value = match.groups()
            self._check_duplicate_name(name, "variable")
            self.variables[name] = value.strip()

    def _parse_host_def(self, line: str) -> None:
        """Parse host definition: host NAME = spec"""
        match = re.match(r'^host\s+(\w+)\s*=\s*(.+)$', line)
        if match:
            name, value = match.groups()
            self._check_duplicate_name(name, "host")
            self.hosts[name] = self._interpolate(value.strip())

    def _parse_storage_def(self, line: str) -> None:
        """Parse storage definition: storage NAME = spec"""
        match = re.match(r'^storage\s+(\w+)\s*=\s*(.+)$', line)
        if match:
            name, value = match.groups()
            self._check_duplicate_name(name, "storage")
            self.storages[name] = self._interpolate(value.strip())

    def _parse_control(self, line: str) -> None:
        """Parse control command: command args"""
        parts = self._split_args(line)
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
        """Parse execute command: @session [timeout=N] > command"""
        # Split on ' > ' to separate host part from command
        parts = line.split(' > ', 1)
        if len(parts) != 2:
            return

        host_part = parts[0].strip()
        commands = parts[1].strip()

        # Check for background execution
        background = commands.endswith('&')
        if background:
            commands = commands[:-1].strip()

        # Parse host and optional timeout
        timeout = 0
        host_tokens = host_part.split()
        host = host_tokens[0]

        for token in host_tokens[1:]:
            if token.startswith('timeout='):
                timeout = self._parse_duration(token[8:])

        # Strip @ prefix from session
        if host.startswith('@'):
            host = host[1:]

        self.steps.append(DSLStep(
            type=StepType.EXECUTE,
            line_num=self.line_num,
            raw=line,
            host=host,
            commands=self._interpolate(commands),
            background=background,
            timeout=timeout,
        ))

    def _parse_transfer(self, line: str) -> None:
        """Parse transfer: source -> dest"""
        source, dest = line.split(' -> ', 1)
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
        """Parse wait command: wait @session condition timeout=N"""
        content = line[5:].strip()  # Strip 'wait '

        target = ""
        pattern = ""
        condition = ""
        timeout = 300  # default 5 minutes

        # Extract host (first @word)
        host_match = re.match(r'^@(\w+)\s*', content)
        if host_match:
            target = host_match.group(1)
            content = content[host_match.end():].strip()
        else:
            raise DSLParseError("wait requires a @session target", self.line_num)

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
                condition = f"file:{self._interpolate(value)}"
            elif key == 'port':
                condition = f"port:{value}"
            elif key == 'idle' and value.lower() == 'true':
                condition = "idle"

        # Check for standalone 'idle' keyword
        if 'idle' in content and 'idle=' not in content:
            condition = "idle"

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
        """Interpolate $VAR and ${VAR} references."""
        # First handle ${VAR} syntax
        def replace_braced(match):
            var_name = match.group(1)
            if var_name.startswith('secret:'):
                return match.group(0)  # Keep secret refs as-is
            return self.variables.get(var_name, match.group(0))

        text = re.sub(r'\$\{(\w+(?::\w+)?)\}', replace_braced, text)

        # Then handle $VAR syntax (but not ${VAR} which was already handled)
        def replace_simple(match):
            var_name = match.group(1)
            return self.variables.get(var_name, match.group(0))

        text = re.sub(r'\$(\w+)(?!\{)', replace_simple, text)

        return text

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
