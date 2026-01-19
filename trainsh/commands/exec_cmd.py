# tmux-trainsh exec command
# Execute DSL commands directly from command line

import sys
from typing import Optional, List

usage = '''<dsl-command>

Execute DSL commands directly without a recipe file.

Examples:
  train exec 'host gpu = user@server
  tmux.open @gpu as work
  @work > nvidia-smi'
  train exec 'host gpu = user@server
  @gpu > uname -a'
  train exec '@gpu:/data -> ./local/'

The DSL syntax is the same as recipe files:
  - var NAME = value       Define a variable
  - host NAME = spec       Define a host
  - storage NAME = spec    Define a storage
  - tmux.open @host as name Create tmux session on host
  - @session > command     Execute command in session
  - @src:path -> @dst:path Transfer files
  - wait @session condition Wait for condition

For train exec, @name resolves to a tmux session first; if none exists, it runs
directly on the host named @name (no tmux session is created).
'''


def main(args: List[str]) -> Optional[str]:
    """Main entry point for exec command."""
    if not args or args[0] in ("-h", "--help", "help"):
        print(usage)
        return None

    # Join all arguments as DSL content
    # Support both single string and multiple arguments
    dsl_content = " ".join(args)

    # Convert escaped newlines to actual newlines
    dsl_content = dsl_content.replace("\\n", "\n")

    # Parse and execute
    from ..core.dsl_parser import parse_recipe_string
    from ..core.dsl_executor import DSLExecutor

    try:
        recipe = parse_recipe_string(dsl_content, name="exec")
    except Exception as e:
        print(f"Parse error: {e}")
        sys.exit(1)

    if not recipe.steps:
        print("No executable steps found in DSL command.")
        print("Make sure your command includes at least one action like:")
        print("  tmux.open @host as session")
        print("  @session > command")
        print("  @src:path -> @dst:path")
        sys.exit(1)

    # Execute
    executor = DSLExecutor(recipe, log_callback=print, allow_host_execute=True)
    success = executor.execute()

    if not success:
        sys.exit(1)

    return None


if __name__ == "__main__":
    main(sys.argv[1:])
elif __name__ == "__doc__":
    cd = sys.cli_docs  # type: ignore
    cd["usage"] = usage
    cd["help_text"] = "Execute DSL commands directly"
    cd["short_desc"] = "Execute DSL commands"
