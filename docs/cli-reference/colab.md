# Colab

Manage Google Colab hosts.

## When to use it

- Register or connect a Colab-backed host.

## Command

```bash
train colab --help
```

## CLI help output

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
