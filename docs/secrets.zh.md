# Secrets 管理

tmux-trainsh 提供了一套安全方式，用于管理 API key、token 和其他凭据，底层依赖操作系统原生 keychain。

> 说明：下面的例子使用当前的 Python recipe DSL。`${secret:name}` 插值在 recipe 命令中的行为与之前一致。

## 总览

Secrets 保存在：

- **macOS**：Keychain Access
- **Windows**：Credential Manager
- **Linux**：Secret Service（如 GNOME Keyring、KWallet）

因此敏感信息会以静态加密形式保存在系统安全设施中。

## 在 Recipe 中使用 Secrets

### 语法

在 recipe 中使用 `${secret:name}` 引用 secret：

```python
from trainsh.pyrecipe import *

recipe("secret-demo")
host("gpu", "$HOST_ID")

auth = shell("""
export HF_TOKEN=${secret:huggingface/token}
export WANDB_API_KEY=${secret:wandb/api_key}
export GITHUB_TOKEN=${secret:github/token}

huggingface-cli login --token $HF_TOKEN
wandb login --relogin
""", host="gpu")
```

### 变量与 Secret 插值的区别

| 语法 | 来源 | 存储方式 | 典型用途 |
| --- | --- | --- | --- |
| `${var_name}` | Recipe 变量 | 明文存在 recipe 文件里 | 路径、实例 ID、配置值 |
| `${secret:name}` | OS Keychain | 由操作系统加密 | API key、token、密码 |

## 管理 Secrets

### 通过 CLI

```bash
train secrets set github/token
train secrets set huggingface/token
train secrets list
train secrets get github/token
train secrets delete github/token
```

### 命名建议

建议用正斜杠按服务组织：

```text
github/token
huggingface/token
huggingface/write_token
wandb/api_key
openai/api_key
anthropic/api_key
kaggle/username
kaggle/key
```

## 常见 Secret

| 名称 | 说明 | 获取方式 |
| --- | --- | --- |
| `github/token` | GitHub Personal Access Token | GitHub → Settings → Developer settings → Personal access tokens |
| `huggingface/token` | HuggingFace User Access Token | huggingface.co → Settings → Access Tokens |
| `wandb/api_key` | Weights & Biases API Key | wandb.ai → Settings → API Keys |
| `openai/api_key` | OpenAI API Key | platform.openai.com → API Keys |
| `kaggle/username` | Kaggle 用户名 | 你的 Kaggle 用户名 |
| `kaggle/key` | Kaggle API Key | kaggle.com → Account → API → Create New Token |

## 例子：训练私有 HuggingFace 模型

```python
from trainsh.pyrecipe import *

recipe("train-private-model")
host("gpu", "vast:12345")
var("MODEL_REPO", "my-org/my-private-model")
var("REMOTE_WORKDIR", "/workspace/train")

hf_login = shell("""
export HF_TOKEN=${secret:huggingface/token}
huggingface-cli login --token $HF_TOKEN --add-to-git-credential
echo \"Logged in to HuggingFace\"
""", host="gpu")

main = session("train", on="gpu", after=hf_login)
clone_model = main(
    "git clone https://huggingface.co/${MODEL_REPO} ${REMOTE_WORKDIR}/model",
    after=hf_login,
)
train = main.bg("""
export WANDB_API_KEY=${secret:wandb/api_key}
python train.py --model ${REMOTE_WORKDIR}/model --wandb-project my-project
""", after=clone_model)
```

## 安全说明

1. Secret 不会直接写进 recipe 文件，文件中只会出现 `${secret:huggingface/token}` 这类引用。
2. Secret 会在运行时解析，只有 step 真正执行时才从 keychain 读取。
3. Secret 会通过环境变量注入到命令执行环境中。
4. 系统可能要求你通过密码或生物识别确认 keychain 访问。

## 故障排查

### 找不到 Secret

如果出现 `Secret 'github/token' not found`：

1. 执行 `train secrets list`
2. 确认名称完全一致
3. 用 `train secrets set <name>` 重新写入

### Keychain 访问被拒绝

在 macOS 上，系统可能弹窗询问是否允许 `python` 或 `train` 访问 keychain。通常建议选择 “Always Allow”。

### Linux 没有 Secret Service

安装并配置 Secret Service：

```bash
# GNOME (Ubuntu, Fedora)
sudo apt install gnome-keyring  # or dnf install

# KDE
sudo apt install kwalletmanager
```
