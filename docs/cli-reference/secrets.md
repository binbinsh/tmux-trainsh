# Secrets

Store and inspect API keys and credentials.

## When to use it

- Set provider tokens.
- Inspect which secrets already exist.

## Command

```bash
train secrets --help
```

## CLI help output

```text
[subcommand] [args...]

Subcommands:
  list             - List configured secrets
  set <key>        - Set a secret (prompts for value)
  get <key>        - Get a secret value
  delete <key>     - Delete a secret
  backend          - Show or switch secrets backend

Predefined keys:
  VAST_API_KEY           - Vast.ai API key
  HF_TOKEN               - HuggingFace token
  OPENAI_API_KEY         - OpenAI API key
  ANTHROPIC_API_KEY      - Anthropic API key
  GITHUB_TOKEN           - GitHub personal access token
```
