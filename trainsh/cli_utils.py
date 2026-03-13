# CLI helper utilities

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping, Optional, Sequence


@dataclass(frozen=True)
class SubcommandSpec:
    """Declarative help metadata for a command subcommand."""

    name: str
    summary: str
    aliases: tuple[str, ...] = ()


def prompt_input(prompt: str, default: Optional[str] = None) -> Optional[str]:
    """Prompt for input and handle EOF/interrupt gracefully."""
    try:
        value = input(prompt)
    except (EOFError, KeyboardInterrupt):
        print("\nCancelled.")
        return None

    value = value.strip()
    if value == "" and default is not None:
        return default
    return value


def render_subcommand_table(subcommands: Sequence[SubcommandSpec]) -> list[str]:
    """Render aligned subcommand rows with optional aliases."""
    if not subcommands:
        return []

    labels = []
    for spec in subcommands:
        label = spec.name
        if spec.aliases:
            label += f" (aliases: {', '.join(spec.aliases)})"
        labels.append(label)

    width = max(len(label) for label in labels)
    return [f"  {label:<{width}}  {spec.summary}" for label, spec in zip(labels, subcommands)]


def render_command_help(
    *,
    command: str,
    summary: str,
    usage_lines: Sequence[str],
    subcommands: Sequence[SubcommandSpec] = (),
    options: Sequence[str] = (),
    examples: Sequence[str] = (),
    notes: Sequence[str] = (),
    see_also: Sequence[str] = (),
) -> str:
    """Render consistent command-local help text."""
    lines = [
        f"{command}",
        f"  {summary}",
        "",
        "Usage",
    ]
    lines.extend(f"  {line}" for line in usage_lines)

    if subcommands:
        lines.extend(["", "Subcommands"])
        lines.extend(render_subcommand_table(subcommands))

    if options:
        lines.extend(["", "Options"])
        lines.extend(f"  {line}" for line in options)

    if notes:
        lines.extend(["", "Notes"])
        lines.extend(f"  {line}" for line in notes)

    if examples:
        lines.extend(["", "Examples"])
        lines.extend(f"  {line}" for line in examples)

    if see_also:
        lines.extend(["", "See Also"])
        lines.extend(f"  {line}" for line in see_also)

    return "\n".join(lines)


def dispatch_subcommand(
    subcommand: str,
    *,
    commands: Mapping[str, Callable[[list[str]], None]],
    aliases: Optional[Mapping[str, str]] = None,
) -> Callable[[list[str]], None]:
    """Resolve a canonical subcommand handler with alias support."""
    canonical = (aliases or {}).get(subcommand, subcommand)
    handler = commands.get(canonical)
    if handler is None:
        raise KeyError(subcommand)
    return handler
