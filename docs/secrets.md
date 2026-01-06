# Secrets Management

Doppio provides a secure way to manage API keys, tokens, and other credentials using your operating system's native keychain.

## Overview

Secrets are stored in:
- **macOS**: Keychain Access
- **Windows**: Credential Manager
- **Linux**: Secret Service (GNOME Keyring, KWallet, etc.)

This ensures your sensitive data is encrypted at rest and protected by your system's security features.

## Using Secrets in Recipes

### Syntax

Reference secrets in your recipe using the `${secret:name}` syntax:

```toml
[[step]]
id = "setup_auth"
ssh_command = { host_id = "${host_id}", command = """
export HF_TOKEN=${secret:huggingface/token}
export WANDB_API_KEY=${secret:wandb/api_key}
export GITHUB_TOKEN=${secret:github/token}

huggingface-cli login --token $HF_TOKEN
wandb login --relogin
""" }
```

### Variable vs Secret Interpolation

| Syntax | Source | Storage | Use Case |
|--------|--------|---------|----------|
| `${var_name}` | Recipe `variables` | Plain text in recipe TOML | Paths, instance IDs, config values |
| `${secret:name}` | OS Keychain | Encrypted by OS | API keys, tokens, passwords |

## Managing Secrets

### Via Settings UI

1. Open Doppio → Settings → Secrets
2. Click "Add Secret" or choose a suggested template
3. Enter the name and value
4. Click Save

### Secret Naming Convention

Use forward slashes to organize secrets by service:

```
github/token
huggingface/token
huggingface/write_token
wandb/api_key
openai/api_key
anthropic/api_key
kaggle/username
kaggle/key
```

## Common Secrets

| Name | Description | How to Get |
|------|-------------|------------|
| `github/token` | GitHub Personal Access Token | GitHub → Settings → Developer settings → Personal access tokens |
| `huggingface/token` | HuggingFace User Access Token | huggingface.co → Settings → Access Tokens |
| `wandb/api_key` | Weights & Biases API Key | wandb.ai → Settings → API Keys |
| `openai/api_key` | OpenAI API Key | platform.openai.com → API Keys |
| `kaggle/username` | Kaggle Username | Your Kaggle username |
| `kaggle/key` | Kaggle API Key | kaggle.com → Account → API → Create New Token |

## Example: Training with Private HuggingFace Model

```toml
[recipe]
name = "train-private-model"
version = "1.0.0"

[variables]
host_id = "vast-12345"
model_repo = "my-org/my-private-model"
remote_workdir = "/workspace/train"

[[step]]
id = "hf_login"
ssh_command = { host_id = "${host_id}", command = """
export HF_TOKEN=${secret:huggingface/token}
huggingface-cli login --token $HF_TOKEN --add-to-git-credential
echo \"Logged in to HuggingFace\"
""" }

[[step]]
id = "clone_model"
depends_on = ["hf_login"]
ssh_command = { host_id = "${host_id}", command = "git clone https://huggingface.co/${model_repo} ${remote_workdir}/model" }

[[step]]
id = "train"
depends_on = ["clone_model"]
tmux_new = { host_id = "${host_id}", session_name = "train", command = """
export WANDB_API_KEY=${secret:wandb/api_key}
python train.py --model ${remote_workdir}/model --wandb-project my-project
""" }
```

## Security Notes

1. **Secrets never appear in recipe files** - Only references like `${secret:huggingface/token}` are stored
2. **Secrets are resolved at runtime** - Values are fetched from keychain only when the step executes
3. **Secrets are injected via environment** - They're passed to remote commands as environment variables
4. **Keychain access may require authentication** - Your OS may prompt for password/biometrics

## Troubleshooting

### Secret not found

If you see an error like `Secret 'github/token' not found`:

1. Go to Settings → Secrets
2. Check if the secret exists with the exact name
3. Add the secret if missing

### Keychain access denied

On macOS, you may see a prompt asking to allow Doppio to access the keychain. Click "Always Allow" to prevent future prompts.

### Linux: No secret service available

Install and configure a secret service:

```bash
# GNOME (Ubuntu, Fedora)
sudo apt install gnome-keyring  # or dnf install

# KDE
sudo apt install kwalletmanager
```
