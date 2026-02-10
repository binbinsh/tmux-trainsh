#!/usr/bin/env bash
# Pre-commit consistency check for tmux-trainsh.
# Validates that DSL_SYNTAX, COMMANDS_REGISTRY, and README are in sync.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

# Use python3 if available, fall back to python
PYTHON="${PYTHON:-$(command -v python3 || command -v python)}"

errors=0

# 1. Check every CONTROL_COMMANDS entry exists in DSL_SYNTAX
echo "Checking CONTROL_COMMANDS vs DSL_SYNTAX..."
missing=$($PYTHON -c "
import sys
sys.path.insert(0, '.')
from trainsh.core.dsl_parser import CONTROL_COMMANDS, DSL_SYNTAX

# Collect all command names mentioned in DSL_SYNTAX control section
syntax_text = ''
for section in DSL_SYNTAX:
    if section.get('id') == 'control':
        syntax_text = section.get('content', '') + ' ' + section.get('description', '')
        break

missing = []
for cmd in sorted(CONTROL_COMMANDS):
    if cmd not in syntax_text:
        missing.append(cmd)

if missing:
    print('\n'.join(missing))
")
if [ -n "$missing" ]; then
    echo "ERROR: CONTROL_COMMANDS entries missing from DSL_SYNTAX:"
    echo "$missing" | sed 's/^/  /'
    errors=1
else
    echo "  OK"
fi

# 2. Check every command in main.py routing exists in COMMANDS_REGISTRY
echo "Checking command routing vs COMMANDS_REGISTRY..."
missing=$($PYTHON -c "
import sys
sys.path.insert(0, '.')
from trainsh.main import COMMANDS_REGISTRY

# Commands routed in main()
routed = {
    'run', 'exec', 'vast', 'transfer', 'recipe', 'host',
    'storage', 'secrets', 'colab', 'pricing', 'update',
    'config', 'help', 'version',
}

registered = {entry['command'] for entry in COMMANDS_REGISTRY}

missing = sorted(routed - registered)
if missing:
    print('\n'.join(missing))
")
if [ -n "$missing" ]; then
    echo "ERROR: Routed commands missing from COMMANDS_REGISTRY:"
    echo "$missing" | sed 's/^/  /'
    errors=1
else
    echo "  OK"
fi

# 3. Check README is up to date
echo "Checking README.md freshness..."
if ! $PYTHON scripts/update_readme.py --check; then
    errors=1
fi

if [ "$errors" -ne 0 ]; then
    echo ""
    echo "Pre-commit check FAILED. Fix the issues above before committing."
    exit 1
fi

echo ""
echo "All checks passed."
