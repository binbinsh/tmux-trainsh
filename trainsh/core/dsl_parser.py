# tmux-trainsh DSL parser
# Parses .recipe files into Recipe objects

import re
from typing import Optional, List, Dict, Set
from dataclasses import dataclass, field
from enum import Enum


class StepType(Enum):
    """Type of DSL step."""
    CONTROL = "control"      # command args (e.g., vast.pick, tmux.open)
    EXECUTE = "execute"      # @host > command
    TRANSFER = "transfer"    # @src:path -> @dst:path
    WAIT = "wait"            # wait @host condition


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

    New Syntax:
        # Variables (reference with $NAME or ${NAME})
        var NAME = value

        # Hosts (reference with @NAME)
        host NAME = spec

        # Storage (reference with @NAME)
        storage NAME = spec

        # Control commands
        vast.pick @host options
        tmux.open @host
        notify "message"

        # Execute commands
        @host > command
        @host > command &
        @host timeout=2h > command

        # Wait commands
        wait @host "pattern" timeout=2h
        wait @host file=path timeout=1h
        wait @host idle timeout=30m

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
        # For backward compatibility with --- blocks
        self.in_var_block = False

    def parse(self, content: str, name: str = "") -> DSLRecipe:
        """Parse DSL content into a recipe."""
        self.variables = {}
        self.hosts = {}
        self.storages = {}
        self.defined_names = set()
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

        # Backward compatibility: variable block delimiter
        if stripped == '---':
            self.in_var_block = not self.in_var_block
            return

        # Inside variable block (backward compatibility)
        if self.in_var_block:
            self._parse_legacy_variable(stripped)
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

        # New syntax: wait @host condition
        if stripped.startswith('wait '):
            self._parse_wait(stripped)
            return

        # Transfer: source -> dest or source <- dest
        if ' -> ' in stripped or ' <- ' in stripped:
            self._parse_transfer(stripped)
            return

        # New syntax: @host > command (execute)
        if ' > ' in stripped and stripped.startswith('@'):
            self._parse_execute(stripped)
            return

        # Control command: command args (e.g., vast.pick @gpu, tmux.open @host)
        # Check if line starts with a known control command
        first_word = stripped.split()[0] if stripped.split() else ""
        if first_word in CONTROL_COMMANDS:
            self._parse_control(stripped)
            return

        # Unknown line - ignore silently for forward compatibility
        pass

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
        """Parse execute command: @host [timeout=N] > command"""
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

        # Strip @ prefix from host
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
        """Parse wait command: wait @host condition timeout=N"""
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
