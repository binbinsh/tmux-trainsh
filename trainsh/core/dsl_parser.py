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


# ---------------------------------------------------------------------------
# DSL_SYNTAX – single source of truth for all recipe DSL documentation.
# Each entry is a dict with keys: title, description (optional), content.
# generate_syntax_reference() renders them as markdown.
# ---------------------------------------------------------------------------

DSL_SYNTAX: List[Dict] = [
    {
        "title": "Quick Example",
        "content": """\
```
# Variables
var MODEL = llama-7b
var WORKDIR = /workspace/train

# Hosts (machines)
host gpu = placeholder
host backup = myserver

# Storage
storage output = r2:my-bucket

# Workflow
vast.pick @gpu num_gpus=1 min_gpu_ram=24
vast.start
vast.wait timeout=5m

# Create a tmux session "work" on the gpu host
tmux.open @gpu as work

# Commands reference the session name, not the host
@work > cd $WORKDIR && git clone https://github.com/user/repo
@work > pip install -r requirements.txt
@work > python train.py --model $MODEL &

wait @work idle timeout=2h
notify "Training finished"

# Transfers reference the host (for SSH connection info)
@gpu:$WORKDIR/model -> @output:/models/$MODEL/
@gpu:$WORKDIR/model -> @backup:/backup/

vast.stop
tmux.close @work
```""",
    },
    {
        "title": "Definitions",
        "description": "All definitions must appear before workflow commands. Names cannot be duplicated across var/host/storage.",
        "content": """\
| Type | Syntax | Reference | Description |
|------|--------|-----------|-------------|
| Variable | `var NAME = value` | `$NAME` | Define a variable |
| Host | `host NAME = spec` | `@NAME` | Define a remote host |
| Storage | `storage NAME = spec` | `@NAME` | Define a storage backend |""",
    },
    {
        "title": "Host Spec Formats",
        "id": "host-spec",
        "content": """\
| Spec | Description |
|------|-------------|
| `placeholder` | Placeholder, must be filled by `vast.pick` |
| `user@hostname` | SSH host |
| `user@hostname -p PORT` | SSH host with port |
| `user@hostname -i KEY` | SSH host with identity file |
| `user@hostname -J JUMP` | SSH host with jump host |
| `user@hostname -o ProxyCommand='CMD'` | SSH host via custom ProxyCommand (e.g. HTTPS tunnel client) |
| `name` | Reference to hosts.toml config |

Cloudflared Access examples:

```bash
# Inline host spec
host case = root@172.16.0.88 -o ProxyCommand='cloudflared access ssh --hostname ssh-access.example.com'
```

```toml
# hosts.toml (primary + fallback candidates)
[[hosts]]
name = "case"
type = "ssh"
hostname = "primary.example.com"
port = 22
username = "root"
env_vars = { connection_candidates = ["ssh://backup.example.com:22", "cloudflared://ssh-access.example.com"] }
```

```toml
# hosts.toml (structured candidates, same as interactive `train host add`)
[[hosts]]
name = "case"
type = "ssh"
hostname = "primary.example.com"
port = 22
username = "root"
env_vars = { connection_candidates = [{ type = "ssh", hostname = "backup.example.com", port = 22 }, { type = "cloudflared", hostname = "ssh-access.example.com" }] }
```""",
    },
    {
        "title": "Storage Spec Formats",
        "id": "storage-spec",
        "content": """\
| Spec | Description |
|------|-------------|
| `placeholder` | Placeholder, must be filled at runtime |
| `r2:bucket` | Cloudflare R2 |
| `b2:bucket` | Backblaze B2 |
| `s3:bucket` | Amazon S3 |
| `name` | Reference to storages.toml config |""",
    },
    {
        "title": "Execute Commands",
        "id": "execute",
        "description": "Run commands in a tmux session (created with `tmux.open`):",
        "content": """\
```
@session > command
@session > command &
@session timeout=2h > command
```

| Syntax | Description |
|--------|-------------|
| `@session > cmd` | Run command, wait for completion |
| `@session > cmd &` | Run command in background |
| `@session timeout=DURATION > cmd` | Run with custom timeout (default: 10m) |

**Note:** The `@session` references a session name from `tmux.open @host as session`, not the host directly.

**Multiline:** Use shell line continuations (`\\`) or heredocs (`<< 'EOF'`) to span commands across lines; the DSL treats them as a single execute step.

**train exec:** `@name` resolves to an existing tmux session first. If none exists, it runs directly on the host named `name` without creating a tmux session.""",
    },
    {
        "title": "Wait Commands",
        "id": "wait",
        "description": "Wait for conditions in a session:",
        "content": """\
```
wait @session "pattern" timeout=DURATION
wait @session file=PATH timeout=DURATION
wait @session port=PORT timeout=DURATION
wait @session idle timeout=DURATION
```

| Condition | Description |
|-----------|-------------|
| `"pattern"` | Wait for regex pattern in terminal output |
| `file=PATH` | Wait for file to exist |
| `port=PORT` | Wait for port to be open |
| `idle` | Wait for no child processes (command finished) |""",
    },
    {
        "title": "Transfer Commands",
        "id": "transfer",
        "description": "Transfer files between endpoints:",
        "content": """\
```
@src:path -> @dst:path
@src:path -> ./local/path
./local/path -> @dst:path
```""",
    },
    {
        "title": "Control Commands",
        "id": "control",
        "description": """\
**tmux session commands:**

The recipe system separates two concepts:
- **Host**: The machine where commands run (defined with `host NAME = spec`)
- **Session**: A persistent tmux session on that host (created with `tmux.open @host as session_name`)

Commands are sent to **sessions**, not hosts directly. This allows multiple sessions on the same host.

```
# WRONG - missing session name
tmux.open @gpu
@gpu > python train.py

# CORRECT - create named session, then use session name
tmux.open @gpu as work
@work > python train.py
tmux.close @work
```""",
        "content": """\
| Command | Description |
|---------|-------------|
| `tmux.open @host as name` | Create tmux session named "name" on host and auto-bridge it to local splits |
| `tmux.close @session` | Close tmux session |
| `tmux.config @host` | Apply tmux configuration to remote host |
| `vast.pick @host [options]` | Interactively select Vast.ai instance |
| `vast.start [id]` | Start Vast.ai instance |
| `vast.stop [id]` | Stop Vast.ai instance |
| `vast.wait [options]` | Wait for instance to be ready |
| `vast.cost [id]` | Show usage cost |
| `notify "message"` | Send styled notification |
| `sleep DURATION` | Sleep for duration |

**notify syntax:**

- `notify "done"`
- `notify training complete`
- `notify "$MODEL finished"`

Styling and delivery are configured globally in `~/.config/tmux-trainsh/config.toml`:

```toml
[notifications]
enabled = true
channels = ["log", "system"]          # log | system | webhook | command
webhook_url = ""                      # used when channels include webhook
command = ""                          # used when channels include command
timeout_secs = 5
fail_on_error = false
```

`system` channel uses macOS `osascript` native notification.

**vast.pick options:**

- `num_gpus=N` - Minimum GPU count
- `min_gpu_ram=N` - Minimum GPU memory (GB)
- `gpu=NAME` - GPU model (e.g., RTX_4090)
- `max_dph=N` - Maximum $/hour
- `limit=N` - Max instances to show

**vast.wait options:**

- `timeout=DURATION` - Max wait time (default: 10m)
- `poll=DURATION` - Poll interval (default: 10s)
- `stop_on_fail=BOOL` - Stop instance on timeout""",
    },
    {
        "title": "Duration Format",
        "id": "duration",
        "content": """\
- `30s` - 30 seconds
- `5m` - 5 minutes
- `2h` - 2 hours
- `300` - 300 seconds (raw number)""",
    },
    {
        "title": "Comments",
        "id": "comments",
        "content": """\
```
# This is a comment
```""",
    },
    {
        "title": "Variable Interpolation",
        "id": "interpolation",
        "content": """\
- `$NAME` - Reference a variable
- `${NAME}` - Reference a variable (alternative)
- `${secret:NAME}` - Reference a secret from secrets store""",
    },
]


def generate_syntax_reference() -> str:
    """Render DSL_SYNTAX as a markdown reference."""
    lines: List[str] = []
    lines.append("Recipe files (`.recipe`) define automated training workflows with a simple DSL.")
    lines.append("")
    for section in DSL_SYNTAX:
        lines.append(f"### {section['title']}")
        lines.append("")
        if section.get("description"):
            lines.append(section["description"])
            lines.append("")
        lines.append(section["content"])
        lines.append("")
    return "\n".join(lines)


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
