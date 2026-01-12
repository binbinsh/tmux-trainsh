# tmux-trainsh: GPU training workflow automation
# License: MIT

__version__ = "0.1.0"


def main(args: list[str]) -> str | None:
    """Entry point for trainsh command."""
    from .main import main as trainsh_main
    return trainsh_main(["trainsh"] + list(args))
