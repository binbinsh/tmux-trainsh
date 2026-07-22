# AGENTS

## 版本规则

- 项目版本使用 `major.yyyy.commit-count`。
- 保持 `pyproject.toml`、CLI 输出和文档里的规范化版本一致。
- 准备提交时，把版本更新到下一个 git commit count，确保提交后的树和 `git rev-list --count HEAD` 匹配。
- 示例：`1.2026.115`

## Pyrecipe 规则

- 仓库内实现文件尽量控制在 800 行以内。
- 文件 basename 应简短清楚，优先显式名称，不使用晦涩缩写。
- 只在代码库已经通用时使用标准技术缩写，例如 `tmux`、`ssh`、`sqlite`。
- basename 尽量不超过 28 个字符；如果更长名称能明显提升可读性，可以例外。
- Python recipe runtime 保持拆分到多个文件中。
- `trainsh/pyrecipe` 实现文件尽量控制在 800 行以内。
- 优先使用显式 Python 对象，不使用字符串迷你 DSL。
- 主 authoring 模型围绕这些对象保持稳定：
  - `Recipe`
  - `Host` / `VastHost` / `HostPath`
  - `Storage` / `StoragePath`
  - `host.tmux(...)`
  - `local.tmux(...)`

## Recipe 优先工作流

- 可重复自动化优先使用 Python recipe authoring，不优先使用临时 `ssh`、`bash` 或手写轮询。
- 一次性远程命令优先使用 `train host run <name> -- <command>` 或 `train vast run <id> -- <command>`，不直接写原始 `ssh`。
- 立即执行优先使用 `train run <recipe>` 或 `train exec <recipe>`。
- 临时一次性 recipe 比创建文件更清楚时，优先使用 `train exec --code ...` 或 `train exec <<'EOF' ... EOF`。
- 需要查看或回忆 recipe 表面时，优先使用 `train recipe show <name>` 和 `train help`。
- Vast 自动化优先使用 `recipe.vast.pick(...)`、`recipe.vast.start(...)` 和 `recipe.vast.wait_ready(...)`。
- 简单 tmux 流程优先使用 `with local.tmux(...) as tmux:` 或 `with gpu.tmux(...) as tmux:`。
- tmux block 默认按文件顺序串联。
- 只有分支 fallback、fan-in/join 或跨 block 依赖需要显式 `depends_on`。
- `depends_on=` 可以是单个 handle，也可以是 handle 列表。
- 对 `train host add` 保存的 host，recipe 中优先直接使用 alias，例如 `Host("gpu-box").tmux("main")`。
- 只有当 handle 会锚定后续阶段或分支时，才保留 Python 变量。
- 后续复用 tmux context 时，优先用名称重新取得，例如 `gpu.tmux("work")`，不要把同一个 Python 变量贯穿整个文件。
- `tmux.after(...)` 只用于设置未来 tmux step 的默认依赖，不要把它当成追溯改写已打开 step 的机制。

## 存储规则

- Hugging Face Buckets 是一等存储 backend，和 `r2`、`b2`、`gcs`、`s3`、`ssh`、local 并列。
- 优先使用命名 storage 或 Python `Storage(...)` 对象，不直接手写 `hf buckets` shell 命令。
- Python recipe 中优先使用显式 storage spec，例如：
  - `Storage("hf:<namespace>/<bucket>")`
  - `Storage("r2:<bucket>")`
  - `Storage({"type": "hf", "config": {"bucket": "<namespace>/<bucket>"}})`
- CLI transfer 的直接 HF endpoint 形式是 `hf:<namespace>/<bucket>:/path`。
- HF buckets 优先使用冒号路径形式，因为 bucket id 本身包含 `/`。
- HF bucket 认证优先使用 `HF_TOKEN` 或 storage-scoped secret，例如 `<STORAGE_NAME>_HF_TOKEN`。
- 在本地路径、host 和 HF buckets 之间移动数据时，优先使用 `train transfer` 或 recipe storage step，不直接调用 `hf buckets sync`。
- recipe 中创建 bucket 时，优先使用 `recipe.storage_ensure_bucket(...)`。

## Runtime 保证

- `.pyrecipe` 仍按 `load -> depends_on 依赖图 -> executor run` 执行。
- Airflow 风格的 retry、timeout、callback、trigger-rule 语义继续支持。
- 支持的 executor alias 包括：
  - `sequential`
  - `thread_pool`
  - `process_pool`
  - `local`
  - `airflow`
  - `celery`
  - `dask`
  - `debug`
- Kubernetes executor 仍不支持。

## 文档和帮助

- `train --help`、`train help` 和命令级 `--help` 必须易于导航。
- README 是入口概览，CLI help 是规范命令参考。

## 回归命令

```bash
python3 tests/test_commands.py
python3 -m unittest tests.test_runtime_persist tests.test_pyrecipe_runtime tests.test_runtime_semantics tests.test_provider_dispatch tests.test_ti_dependencies
uv run --with coverage python scripts/check_runtime_coverage.py
```
