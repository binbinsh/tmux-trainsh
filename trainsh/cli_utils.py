# CLI helper utilities

from typing import Optional


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
