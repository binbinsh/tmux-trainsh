# Colab

管理 Google Colab 主机。

## 何时使用

- 注册或连接一个 Colab 主机。

## 命令

```bash
train colab --help
```

## CLI 帮助输出

```text
[subcommand] [args...]

Subcommands:
  list             - List connected Colab notebooks
  connect          - Connect to a Colab runtime
  run <cmd>        - Run command on Colab
  ssh              - SSH into Colab (requires ngrok/cloudflared)

Note: Google Colab integration requires:
  1. A running Colab notebook with SSH enabled
  2. ngrok or cloudflared for tunneling
  3. The tunnel URL/connection info

Example Colab setup code:
  !pip install colab_ssh
  from colab_ssh import launch_ssh_cloudflared
  launch_ssh_cloudflared(password="your_password")
```
