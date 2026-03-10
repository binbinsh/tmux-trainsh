# 密钥

存储并查看 API key 与凭据。

## 何时使用

- 设置各类 provider token。
- 检查已经存在的密钥条目。

## 命令

```bash
train secrets --help
```

## CLI 帮助输出

```text
[subcommand] [args...]

Subcommands:
  list             - List configured secrets
  set <key>        - Set a secret (prompts for value)
  get <key>        - Get a secret value
  delete <key>     - Delete a secret

Predefined keys:
  VAST_API_KEY           - Vast.ai API key
  HF_TOKEN               - HuggingFace token
  OPENAI_API_KEY         - OpenAI API key
  ANTHROPIC_API_KEY      - Anthropic API key
  GITHUB_TOKEN           - GitHub personal access token
```
