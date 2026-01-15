# tmux-trainsh: GPU training workflow automation
# License: MIT

from importlib.metadata import version, PackageNotFoundError

try:
    __version__ = version("tmux-trainsh")
except PackageNotFoundError:
    __version__ = "0.0.0-dev"


def main(args: list[str]) -> str | None:
    """Entry point for trainsh command."""
    from .main import main as trainsh_main
    return trainsh_main(["trainsh"] + list(args))
