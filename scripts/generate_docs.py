#!/usr/bin/env python3
"""Generate the trainsh documentation reference pages."""

from __future__ import annotations

import argparse
import inspect
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
SOURCE_DOCS_DIR = ROOT / "docs"

sys.path.insert(0, str(ROOT))

from trainsh.pyrecipe import load_python_recipe, recipe  # noqa: E402
from trainsh.pyrecipe import authoring as authoring_api  # noqa: E402
from trainsh.pyrecipe.session_steps import RecipeSessionRef  # noqa: E402


@dataclass(frozen=True)
class CliPage:
    slug: str
    title: str
    title_zh: str
    summary: str
    summary_zh: str
    command: str
    args: tuple[str, ...]
    use_cases: tuple[str, ...] = ()
    use_cases_zh: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
    notes_zh: tuple[str, ...] = ()


@dataclass(frozen=True)
class ApiPage:
    slug: str
    title: str
    title_zh: str
    builder: str
    description: str
    description_zh: str
    usage: str
    scenarios: tuple[str, ...]
    scenarios_zh: tuple[str, ...]
    cls: type | None = None
    members: tuple[tuple[str, object], ...] = ()


@dataclass(frozen=True)
class PublicObjectDoc:
    name: str
    member: object
    summary: str
    summary_zh: str


CLI_PAGES: tuple[CliPage, ...] = (
    CliPage(
        slug="help",
        title="Help Hub",
        title_zh="帮助中心",
        summary="Centralized help topics and entry points.",
        summary_zh="集中查看帮助主题和命令入口。",
        command="train help",
        args=("help",),
        use_cases=(
            "Find the right command without reading the full site first.",
            "Jump to recipe syntax with `train help recipe`.",
        ),
        use_cases_zh=(
            "在不通读整站文档的情况下快速找到正确命令。",
            "通过 `train help recipe` 直接进入 recipe 语法说明。",
        ),
        notes=(
            "Use `train help recipe` for syntax and examples.",
            "Use `train <command> --help` for command-local flags.",
        ),
        notes_zh=(
            "使用 `train help recipe` 查看语法和示例。",
            "使用 `train <command> --help` 查看命令自己的参数。",
        ),
    ),
    CliPage(
        slug="run",
        title="Run",
        title_zh="运行",
        summary="Run one recipe immediately.",
        summary_zh="立即执行一个 recipe。",
        command="train run --help",
        args=("run", "--help"),
        use_cases=(
            "Start a workflow on demand.",
            "Override variables or hosts for one run.",
        ),
        use_cases_zh=(
            "按需启动一次工作流。",
            "为单次运行覆盖变量或主机映射。",
        ),
    ),
    CliPage(
        slug="resume",
        title="Resume",
        title_zh="恢复",
        summary="Resume the latest interrupted or failed run for one recipe.",
        summary_zh="恢复某个 recipe 最近一次中断或失败的运行。",
        command="train resume --help",
        args=("resume", "--help"),
        use_cases=(
            "Continue from the latest persisted runtime state.",
            "Restart after interruption without rebuilding tmux state manually.",
        ),
        use_cases_zh=(
            "从最近一次持久化的运行时状态继续执行。",
            "在中断后恢复执行，而不需要手工重建 tmux 状态。",
        ),
        notes=("Resume restores saved hosts and tmux state. Only `--var` overrides are supported.",),
        notes_zh=("`resume` 会恢复已保存的主机解析和 tmux 状态，只支持 `--var` 覆盖。",),
    ),
    CliPage(
        slug="status",
        title="Status",
        title_zh="状态",
        summary="Inspect active and recent sessions.",
        summary_zh="查看当前和最近的会话状态。",
        command="train status --help",
        args=("status", "--help"),
        use_cases=("See which jobs are still running.", "Check the latest session state before resuming."),
        use_cases_zh=("查看哪些任务仍在运行。", "在恢复前检查最近一次会话状态。"),
    ),
    CliPage(
        slug="logs",
        title="Logs",
        title_zh="日志",
        summary="Inspect execution logs for the current or a specific job.",
        summary_zh="查看当前任务或指定任务的执行日志。",
        command="train logs --help",
        args=("logs", "--help"),
        use_cases=("Tail recent logs while debugging.", "Fetch logs for a completed or failed run."),
        use_cases_zh=("调试时跟踪最新日志。", "查看已完成或失败运行的日志。"),
    ),
    CliPage(
        slug="jobs",
        title="Jobs",
        title_zh="任务历史",
        summary="Inspect recent job state history.",
        summary_zh="查看最近的任务状态历史。",
        command="train jobs --help",
        args=("jobs", "--help"),
        use_cases=("Review recent runs across recipes.", "Find job ids before checking logs."),
        use_cases_zh=("回顾多个 recipe 的最近运行。", "在查看日志前先找到 job id。"),
    ),
    CliPage(
        slug="schedule",
        title="Schedule",
        title_zh="调度",
        summary="Run and inspect timed recipes.",
        summary_zh="查看和运行定时 recipe。",
        command="train schedule --help",
        args=("schedule", "--help"),
        use_cases=("List scheduled recipes.", "Run the scheduler once or as a long-lived service."),
        use_cases_zh=("列出已配置调度的 recipe。", "以单次模式或常驻模式运行调度器。"),
    ),
    CliPage(
        slug="recipes",
        title="Recipes",
        title_zh="Recipe 文件",
        summary="Manage Python recipe files and starter templates.",
        summary_zh="管理 Python recipe 文件和模板。",
        command="train recipes --help",
        args=("recipes", "--help"),
        use_cases=("Create a new recipe from a starter template.", "Inspect or print bundled recipes."),
        use_cases_zh=("从模板创建新的 recipe。", "查看或打印内置 recipe。"),
        notes=(
            "Syntax lives in [Python Recipes](../python-recipes.md) and [Package Reference](../package-reference/_index.md).",
        ),
        notes_zh=(
            "语法说明在 [Python Recipes](../python-recipes.md) 和 [Package Reference](../package-reference/_index.md)。",
        ),
    ),
    CliPage(
        slug="transfer",
        title="Transfer",
        title_zh="传输",
        summary="Copy data between hosts and storage backends.",
        summary_zh="在主机和存储后端之间复制数据。",
        command="train transfer --help",
        args=("transfer", "--help"),
        use_cases=("Move artifacts off a remote host.", "Sync files between local paths and storage backends."),
        use_cases_zh=("把产物从远端主机拉回本地。", "在本地路径和存储后端之间同步文件。"),
    ),
    CliPage(
        slug="host",
        title="Host",
        title_zh="主机",
        summary="Manage SSH, local, Colab, and Vast-backed hosts.",
        summary_zh="管理 SSH、本地、Colab 和 Vast 主机。",
        command="train host --help",
        args=("host", "--help"),
        use_cases=("Register and test SSH hosts.", "Open an SSH session into a configured host."),
        use_cases_zh=("注册并测试 SSH 主机。", "连接到已配置主机的 SSH 会话。"),
    ),
    CliPage(
        slug="storage",
        title="Storage",
        title_zh="存储",
        summary="Manage storage backends such as local paths, R2, B2, and S3.",
        summary_zh="管理本地路径、R2、B2、S3 等存储后端。",
        command="train storage --help",
        args=("storage", "--help"),
        use_cases=("Add an object store backend.", "Check whether a storage alias works before using it in recipes."),
        use_cases_zh=("添加对象存储后端。", "在 recipe 中使用前测试存储别名是否可用。"),
    ),
    CliPage(
        slug="secrets",
        title="Secrets",
        title_zh="密钥",
        summary="Store and inspect API keys and credentials.",
        summary_zh="存储并查看 API key 与凭据。",
        command="train secrets --help",
        args=("secrets", "--help"),
        use_cases=("Set provider tokens.", "Inspect which secrets already exist."),
        use_cases_zh=("设置各类 provider token。", "检查已经存在的密钥条目。"),
    ),
    CliPage(
        slug="config",
        title="Config",
        title_zh="配置",
        summary="Inspect and update runtime and tmux configuration.",
        summary_zh="查看和修改运行时与 tmux 配置。",
        command="train config --help",
        args=("config", "--help"),
        use_cases=("Inspect current config values.", "Apply or tweak tmux defaults."),
        use_cases_zh=("查看当前配置值。", "调整或应用 tmux 默认配置。"),
    ),
    CliPage(
        slug="vast",
        title="Vast",
        title_zh="Vast",
        summary="Manage Vast.ai instances.",
        summary_zh="管理 Vast.ai 实例。",
        command="train vast --help",
        args=("vast", "--help"),
        use_cases=("List or start GPU instances.", "Connect recipe hosts to Vast instances."),
        use_cases_zh=("列出或启动 GPU 实例。", "把 recipe 主机关联到 Vast 实例。"),
    ),
    CliPage(
        slug="colab",
        title="Colab",
        title_zh="Colab",
        summary="Manage Google Colab hosts.",
        summary_zh="管理 Google Colab 主机。",
        command="train colab --help",
        args=("colab", "--help"),
        use_cases=("Register or connect a Colab-backed host.",),
        use_cases_zh=("注册或连接一个 Colab 主机。",),
    ),
    CliPage(
        slug="pricing",
        title="Pricing",
        title_zh="价格",
        summary="Inspect exchange rates and estimate costs.",
        summary_zh="查看汇率并估算成本。",
        command="train pricing --help",
        args=("pricing", "--help"),
        use_cases=("Convert costs between currencies.", "Estimate run costs in scripts or ad hoc usage."),
        use_cases_zh=("在不同币种间换算成本。", "在脚本或临时场景中估算运行费用。"),
    ),
    CliPage(
        slug="update",
        title="Update",
        title_zh="更新",
        summary="Check for new trainsh releases.",
        summary_zh="检查 trainsh 的新版本。",
        command="train update --help",
        args=("update", "--help"),
        use_cases=("See whether the installed version is behind.",),
        use_cases_zh=("查看当前安装版本是否落后。",),
    ),
)


API_PAGES: tuple[ApiPage, ...] = (
    ApiPage(
        slug="recipe-builder",
        title="Recipe Authoring",
        title_zh="Recipe 编写",
        builder="recipe(...)",
        description=(
            "The top-level authoring surface is where recipes start. Use these helpers to declare recipe metadata, "
            "variables, host aliases, storage aliases, executor settings, and shared defaults."
        ),
        description_zh="顶层 authoring 语法是 recipe 的起点，用来声明工作流元数据、变量、主机别名、存储别名、执行器设置，以及共享默认项。",
        usage="""from trainsh.pyrecipe import *

recipe("demo", executor="thread_pool", callbacks=["console", "sqlite"])
var("MODEL", "llama-7b")
host("gpu", "user@host")
storage("artifacts", "r2:bucket")""",
        scenarios=(
            "Set up variables and infrastructure aliases before adding steps.",
            "Apply retry, timeout, and trigger defaults that affect many later steps.",
        ),
        scenarios_zh=(
            "在添加步骤前先配置变量、主机和存储别名。",
            "为后续步骤统一设置重试、超时和触发规则默认值。",
        ),
        members=(
            ("recipe", authoring_api.recipe),
            ("defaults", authoring_api.defaults),
            ("var", authoring_api.var),
            ("host", authoring_api.host),
            ("storage", authoring_api.storage),
        ),
    ),
    ApiPage(
        slug="basic-providers",
        title="Basic Providers",
        title_zh="基础 Provider",
        builder="recipe(...)",
        description="These helpers cover shell commands, Python snippets, notifications, and a few direct task primitives.",
        description_zh="这些 helper 覆盖 shell 命令、Python 片段、通知，以及一些直接的任务原语。",
        usage="""probe = shell("echo ready", id="probe")
notice("workflow started", after=probe)""",
        scenarios=(
            "Run simple shell or Python work without dropping to low-level provider specs.",
            "Emit notifications directly from the top-level DSL.",
        ),
        scenarios_zh=(
            "无需手写底层 provider 规格就能执行简单的 shell 或 Python 工作。",
            "直接从顶层 DSL 调用通知类 helper。",
        ),
        members=(
            ("shell", authoring_api.shell),
            ("bash", authoring_api.bash),
            ("python", authoring_api.python),
            ("notice", authoring_api.notice),
            ("fail", authoring_api.fail),
        ),
    ),
    ApiPage(
        slug="workflow-helpers",
        title="Workflow Helpers",
        title_zh="工作流 Helper",
        builder="recipe(...)",
        description="Workflow helpers cover Git actions, host probes, SSH commands, value capture, and lightweight HTTP or file waits.",
        description_zh="工作流 helper 覆盖 Git 操作、主机探测、SSH 命令、变量捕获，以及轻量级的 HTTP 或文件等待。",
        usage="""ready = host_test("gpu")
clone = git_clone("https://github.com/example/project.git", "/workspace/project", after=ready)
port = wait_for_port(8000, host="gpu", after=clone)""",
        scenarios=(
            "Prepare remote workspaces before tmux sessions start.",
            "Probe files, ports, or HTTP endpoints as part of orchestration.",
        ),
        scenarios_zh=(
            "在 tmux 会话开始前准备远端工作目录。",
            "把文件、端口或 HTTP 端点探测作为编排的一部分。",
        ),
        members=(
            ("host_test", authoring_api.host_test),
            ("git_clone", authoring_api.git_clone),
            ("git_pull", authoring_api.git_pull),
            ("wait_file", authoring_api.wait_file),
            ("wait_for_port", authoring_api.wait_for_port),
            ("set_env", authoring_api.set_env),
        ),
    ),
    ApiPage(
        slug="control-flow",
        title="Control Flow",
        title_zh="控制流",
        builder="recipe(...)",
        description="Control-flow helpers implement latest-only behavior, branching, short-circuit checks, and condition waits.",
        description_zh="控制流 helper 实现 latest-only、分支、短路判断和条件等待等能力。",
        usage="""latest = latest_only(fail_if_unknown=False)
branch = choose("PATH_KIND", when='MODE == "prod"', then="prod", else_="dev", after=latest)
join(after=branch)""",
        scenarios=(
            "Skip stale runs when a newer scheduled run exists.",
            "Build DAG branches that later merge with explicit trigger rules.",
        ),
        scenarios_zh=(
            "在存在更新调度运行时跳过过期运行。",
            "构建 DAG 分支，并在后续用显式 trigger rule 合流。",
        ),
        members=(
            ("latest_only", authoring_api.latest_only),
            ("choose", authoring_api.choose),
            ("short_circuit", authoring_api.short_circuit),
            ("skip_if", authoring_api.skip_if),
            ("skip_if_not", authoring_api.skip_if_not),
            ("join", authoring_api.join),
            ("on_all_done", authoring_api.on_all_done),
            ("on_all_success", authoring_api.on_all_success),
            ("on_none_failed", authoring_api.on_none_failed),
        ),
    ),
    ApiPage(
        slug="session-api",
        title="Session API",
        title_zh="Session API",
        builder='main = session("main", on="gpu")',
        description="A bound session object keeps follow-up steps attached to one tmux session. This is the main API for long-running remote work.",
        description_zh="绑定后的 session 对象会把后续步骤附着到同一个 tmux 会话上，这是表达长时间远端任务的核心 API。",
        usage="""main = session("main", on="gpu")
clone = main("git clone https://github.com/example/project.git /workspace/project")
train = main.bg("cd /workspace/project && python train.py", after=clone)
done = main.idle(timeout="2h", after=train)
main.close(after=done)""",
        scenarios=(
            "Express long-lived training flows in a single session-oriented style.",
            "Wait on pane idleness, output text, files, or ports without leaving tmux semantics.",
        ),
        scenarios_zh=(
            "用统一的 session 风格表达长时间训练流程。",
            "在不离开 tmux 语义的前提下等待空闲、输出文本、文件或端口。",
        ),
        members=(
            ("session", authoring_api.session),
            ("close", authoring_api.close),
            ("bg", RecipeSessionRef.bg),
            ("wait", RecipeSessionRef.wait),
            ("idle", RecipeSessionRef.idle),
            ("file", RecipeSessionRef.file),
            ("port", RecipeSessionRef.port),
        ),
    ),
    ApiPage(
        slug="network",
        title="HTTP and Network",
        title_zh="HTTP 与网络",
        builder="recipe(...)",
        description="HTTP helpers cover direct request aliases, JSON helpers, and polling-style sensors for service health checks.",
        description_zh="HTTP helper 覆盖直接请求别名、JSON helper，以及用于健康检查的轮询式 sensor。",
        usage="""health = http_wait(
    "https://example.com/health",
    status=200,
    timeout="2m",
    every="5s",
)""",
        scenarios=(
            "Gate workflows on a health endpoint or service warm-up check.",
            "Capture HTTP responses into variables for later steps.",
        ),
        scenarios_zh=(
            "通过健康检查端点或服务预热检查来控制工作流启动。",
            "把 HTTP 响应捕获到变量中供后续步骤使用。",
        ),
        members=(
            ("http_get", authoring_api.http_get),
            ("http_post", authoring_api.http_post),
            ("http_put", authoring_api.http_put),
            ("http_delete", authoring_api.http_delete),
            ("http_head", authoring_api.http_head),
            ("http_request", authoring_api.http_request),
            ("http_wait", authoring_api.http_wait),
        ),
    ),
    ApiPage(
        slug="sqlite-and-xcom",
        title="SQLite and XCom",
        title_zh="SQLite 与 XCom",
        builder="recipe(...)",
        description="SQLite helpers run local database queries, while XCom-style helpers persist and retrieve small runtime values through sqlite metadata.",
        description_zh="SQLite helper 用于本地数据库查询，XCom 风格 helper 用于通过 sqlite 元数据持久化和读取小型运行时值。",
        usage="""setup = sql_script("CREATE TABLE IF NOT EXISTS runs(id INTEGER PRIMARY KEY, name TEXT);", db="$SQLITE_DB")
rows = sql_query("SELECT * FROM runs", db="$SQLITE_DB", into="RUNS", after=setup)""",
        scenarios=(
            "Record lightweight workflow metadata during a run.",
            "Pass small values between tasks without editing files.",
        ),
        scenarios_zh=(
            "在运行过程中记录轻量级工作流元数据。",
            "在任务之间传递小型值，而不需要写文件。",
        ),
        members=(
            ("sql_query", authoring_api.sql_query),
            ("sql_exec", authoring_api.sql_exec),
            ("sql_script", authoring_api.sql_script),
            ("xcom_push", authoring_api.xcom_push),
            ("xcom_pull", authoring_api.xcom_pull),
        ),
    ),
    ApiPage(
        slug="notifications-and-misc",
        title="Notifications and Misc",
        title_zh="通知与杂项",
        builder="recipe(...)",
        description="Misc helpers cover explicit failure steps, webhook-style notifications, and XCom push/pull operations.",
        description_zh="杂项 helper 覆盖显式失败步骤、Webhook 风格通知，以及 XCom push/pull 操作。",
        usage="""push = xcom_push("train_loss", value="0.42")
notice("training finished", after=push)""",
        scenarios=(
            "Emit notifications to external systems at key workflow events.",
            "Fail a branch intentionally or pass a small computed value forward.",
        ),
        scenarios_zh=(
            "在关键工作流事件上向外部系统发送通知。",
            "显式让某个分支失败，或向后续步骤传递小型计算值。",
        ),
        members=(
            ("notice", authoring_api.notice),
            ("slack", authoring_api.slack),
            ("telegram", authoring_api.telegram),
            ("discord", authoring_api.discord),
            ("email_send", authoring_api.email_send),
            ("webhook", authoring_api.webhook),
            ("fail", authoring_api.fail),
        ),
    ),
    ApiPage(
        slug="storage",
        title="Storage",
        title_zh="存储",
        builder="recipe(...)",
        description="Storage helpers upload, download, copy, move, sync, inspect, and wait on storage-backed paths.",
        description_zh="存储 helper 提供上传、下载、复制、移动、同步、查看元数据，以及等待存储路径等能力。",
        usage="""upload = storage_upload("./artifacts", "artifacts:/runs/$RUN_NAME")
wait = storage_wait("artifacts", "/runs/$RUN_NAME/done.txt", after=upload)""",
        scenarios=(
            "Publish artifacts to object storage.",
            "Poll for an object or key produced by another system.",
        ),
        scenarios_zh=(
            "把产物发布到对象存储。",
            "轮询另一个系统产出的对象或键。",
        ),
        members=(
            ("storage_upload", authoring_api.storage_upload),
            ("storage_download", authoring_api.storage_download),
            ("storage_wait", authoring_api.storage_wait),
            ("storage_copy", authoring_api.storage_copy),
            ("storage_move", authoring_api.storage_move),
            ("storage_sync", authoring_api.storage_sync),
            ("storage_remove", authoring_api.storage_remove),
        ),
    ),
    ApiPage(
        slug="transfer",
        title="Transfer",
        title_zh="传输",
        builder="recipe(...)",
        description="Transfer helpers move files or directories between local paths, remote hosts, and storage endpoints.",
        description_zh="传输 helper 用于在本地路径、远端主机和存储端点之间移动文件或目录。",
        usage="""copy = transfer("@gpu:/workspace/output", "./output")
mirror = transfer("./checkpoints", "artifacts:/checkpoints", operation="sync")""",
        scenarios=(
            "Pull model outputs from a GPU host.",
            "Sync checkpoints between local and cloud storage.",
        ),
        scenarios_zh=(
            "把模型输出从 GPU 主机拉回本地。",
            "在本地和云存储之间同步 checkpoint。",
        ),
        members=(
            ("transfer", authoring_api.transfer),
        ),
    ),
    ApiPage(
        slug="control-helpers",
        title="Control Helpers",
        title_zh="控制 Helper",
        builder="recipe(...)",
        description="Control helpers manage tmux sessions directly, add sleeps, and define explicit trigger-rule join points.",
        description_zh="控制 helper 用于直接管理 tmux 会话、添加 sleep，以及定义显式 trigger-rule 合流点。",
        usage="""open_main = tmux_open("gpu", as_="main")
pause = sleep("30s", after=open_main)
join = on_all_done(after=pause)""",
        scenarios=(
            "Open or close tmux sessions explicitly outside the bound session API.",
            "Create explicit merge points after branch fan-out.",
        ),
        scenarios_zh=(
            "在绑定 session API 之外显式打开或关闭 tmux 会话。",
            "在分支扇出后创建显式合流点。",
        ),
        members=(
            ("tmux_open", authoring_api.tmux_open),
            ("tmux_close", authoring_api.tmux_close),
            ("tmux_config", authoring_api.tmux_config),
            ("sleep", authoring_api.sleep),
            ("on_all_done", authoring_api.on_all_done),
            ("on_all_failed", authoring_api.on_all_failed),
            ("on_none_failed", authoring_api.on_none_failed),
        ),
    ),
)


PUBLIC_OBJECTS: tuple[PublicObjectDoc, ...] = (
    PublicObjectDoc(
        name="recipe",
        member=recipe,
        summary="Top-level declaration that binds the active recipe for one `.py` file.",
        summary_zh="为单个 `.py` recipe 文件绑定当前活动 recipe 的顶层声明函数。",
    ),
    PublicObjectDoc(
        name="load_python_recipe",
        member=load_python_recipe,
        summary="Load one `.py` recipe file and return its bound recipe object.",
        summary_zh="加载一个 `.py` recipe 文件并返回其绑定后的 recipe 对象。",
    ),
)


EXAMPLE_SUMMARIES = {
    "hello.py": "Minimal local tmux session and notification flow.",
    "aptup.py": "Update a Debian or Ubuntu machine through a managed tmux session.",
    "brewup.py": "Upgrade Homebrew packages and casks on macOS.",
    "feature-tour.py": "Exercise advanced Python recipe features in one workflow.",
    "nanogpt-train.py": "Launch a nanoGPT training run on a Vast-backed GPU host and pull artifacts back.",
    "unsloth-finetune.py": "Fine-tune an Unsloth model on a Vast-backed host and collect outputs locally.",
}

EXAMPLE_SUMMARIES_ZH = {
    "hello.py": "最小化的本地 tmux 会话和通知流程。",
    "aptup.py": "通过受管 tmux 会话更新 Debian 或 Ubuntu 主机。",
    "brewup.py": "在 macOS 上升级 Homebrew 包和 cask。",
    "feature-tour.py": "在一个 workflow 中演示高级 Python recipe 功能。",
    "nanogpt-train.py": "在 Vast GPU 主机上启动 nanoGPT 训练并回收产物。",
    "unsloth-finetune.py": "在 Vast 主机上执行 Unsloth 微调并把输出拉回本地。",
}


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=SOURCE_DOCS_DIR,
        help="Directory where Hugo-ready docs should be written.",
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.rstrip() + "\n", encoding="utf-8")


def localized_path(path: Path, language: str) -> Path:
    if language == "en":
        return path
    suffix = path.suffix
    if not suffix:
        raise ValueError(f"Expected markdown path with suffix: {path}")
    return path.with_name(f"{path.stem}.{language}{suffix}")


def write_localized_text(path: Path, english: str, chinese: str) -> None:
    write_text(path, english)
    write_text(localized_path(path, "zh"), chinese)


def reset_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def reset_generated_dirs(docs_dir: Path) -> None:
    reset_dir(docs_dir / "cli-reference")
    reset_dir(docs_dir / "package-reference")
    reset_dir(docs_dir / "examples")
    legacy_reference = docs_dir / "reference"
    if legacy_reference.exists():
        shutil.rmtree(legacy_reference)


def infer_title(path: Path, text: str) -> str:
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    if path.name == "_index.md":
        return path.parent.name.replace("-", " ").replace("_", " ").title()
    return path.stem.replace("-", " ").replace("_", " ").title()


def ensure_hugo_front_matter(path: Path, text: str) -> str:
    stripped = text.lstrip()
    if stripped.startswith("+++\n") or stripped.startswith("---\n"):
        return text.rstrip() + "\n"
    lines = text.splitlines()
    body_lines = lines
    title = infer_title(path, text)
    for index, line in enumerate(lines):
        if line.startswith("# "):
            title = line[2:].strip()
            body_lines = lines[index + 1 :]
            if body_lines and not body_lines[0].strip():
                body_lines = body_lines[1:]
            break
    body = "\n".join(body_lines).rstrip()
    title = title.replace('"', '\\"')
    front_matter = f'+++\ntitle = "{title}"\ndraft = false\n+++\n\n'
    if body:
        return front_matter + body + "\n"
    return front_matter


def export_hugo_tree(source_dir: Path, output_dir: Path) -> None:
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    for source_path in sorted(source_dir.rglob("*")):
        relative = source_path.relative_to(source_dir)
        target_path = output_dir / relative
        if source_path.is_dir():
            target_path.mkdir(parents=True, exist_ok=True)
            continue
        if source_path.suffix.lower() != ".md":
            shutil.copy2(source_path, target_path)
            continue
        content = source_path.read_text(encoding="utf-8")
        write_text(target_path, ensure_hugo_front_matter(relative, content))


def escape_cell(value: object) -> str:
    return str(value).replace("|", "\\|")


def markdown_table(headers: tuple[str, ...], rows: list[tuple[str, ...]]) -> str:
    body = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    for row in rows:
        body.append("| " + " | ".join(escape_cell(cell) for cell in row) + " |")
    return "\n".join(body)


def format_annotation(annotation: object) -> str:
    if annotation is inspect.Signature.empty:
        return "Any"
    if isinstance(annotation, str):
        text = annotation
    else:
        text = str(annotation)
    text = text.replace("typing.", "")
    aliases = {
        "RecipeSpecCore": "Any",
        "RecipeSpec": "Any",
        "RecipeSessionRef": "Session",
        "PythonRecipeError": "Error",
    }
    for source, target in aliases.items():
        text = text.replace(source, target)
    return text


def normalize_signature_text(text: str) -> str:
    aliases = {
        "RecipeSpecCore": "Any",
        "RecipeSpec": "Any",
        "RecipeSessionRef": "Session",
        "PythonRecipeError": "Error",
    }
    normalized = text.replace("typing.", "")
    for source, target in aliases.items():
        normalized = normalized.replace(source, target)
    return normalized


def format_default(default: object) -> str:
    if default is inspect.Signature.empty:
        return "required"
    if isinstance(default, str):
        return repr(default)
    return repr(default)


def format_signature(name: str, member: object) -> str:
    signature = inspect.signature(member)
    params = visible_parameters(member)
    signature = signature.replace(parameters=params)
    return normalize_signature_text(f"{name}{signature}")


def summarize_doc(member: object) -> str:
    doc = inspect.getdoc(member) or ""
    return doc.split("\n\n", 1)[0].strip()


def method_parameters(member: object) -> list[inspect.Parameter]:
    params = list(inspect.signature(member).parameters.values())
    if params and params[0].name == "self":
        return params[1:]
    return params


def visible_parameters(member: object) -> list[inspect.Parameter]:
    params = method_parameters(member)
    names = {parameter.name for parameter in params}
    if "after" in names:
        params = [
            parameter
            for parameter in params
            if parameter.name not in {"depends_on", "step_options"}
        ]
    return params


def parameter_table(member: object) -> str:
    rows: list[tuple[str, ...]] = []
    for parameter in visible_parameters(member):
        rows.append(
            (
                f"`{parameter.name}`",
                parameter.kind.name.lower(),
                f"`{format_annotation(parameter.annotation)}`",
                f"`{format_default(parameter.default)}`",
            )
        )
    if not rows:
        return "This callable does not declare public parameters."
    return markdown_table(("Parameter", "Kind", "Type", "Default"), rows)


def return_value(member: object) -> str:
    annotation = inspect.signature(member).return_annotation
    return f"`{format_annotation(annotation)}`"


def public_methods(cls: type) -> list[tuple[str, object]]:
    methods: list[tuple[str, object]] = []
    for name, member in cls.__dict__.items():
        if name.startswith("_") or not callable(member):
            continue
        methods.append((name, member))
    return methods


def run_train(args: tuple[str, ...], *, home: Path) -> str:
    env = os.environ.copy()
    env["HOME"] = str(home)
    result = subprocess.run(
        [sys.executable, "-m", "trainsh", *args],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    output = (result.stdout + result.stderr).strip()
    if result.returncode != 0:
        raise RuntimeError(f"`python -m trainsh {' '.join(args)}` failed:\n{output}")
    return output


def generate_cli_reference(docs_dir: Path, home: Path) -> None:
    cli_dir = docs_dir / "cli-reference"
    rows_en: list[tuple[str, ...]] = []
    rows_zh: list[tuple[str, ...]] = []

    for page in CLI_PAGES:
        output = run_train(page.args, home=home)
        use_cases_en = "\n".join(f"- {item}" for item in page.use_cases)
        use_cases_zh = "\n".join(f"- {item}" for item in page.use_cases_zh)
        notes_en = "\n".join(f"- {item}" for item in page.notes)
        notes_zh = "\n".join(f"- {item}" for item in page.notes_zh)
        content_en = f"""# {page.title}

{page.summary}

## When to use it

{use_cases_en or "- Use this command when the workflow naturally maps to it."}

## Command

```bash
{page.command}
```

## CLI help output

```text
{output}
```
"""
        if page.notes:
            content_en += f"""
## Notes

{notes_en}
"""
        content_zh = f"""# {page.title_zh}

{page.summary_zh}

## 何时使用

{use_cases_zh or "- 当你的工作流刚好需要这个命令时，就直接使用它。"}

## 命令

```bash
{page.command}
```

## CLI 帮助输出

```text
{output}
```
"""
        if page.notes_zh:
            content_zh += f"""
## 说明

{notes_zh}
"""
        write_localized_text(cli_dir / f"{page.slug}.md", content_en, content_zh)
        rows_en.append((f"`train {page.slug}`", page.summary, f"[Open]({page.slug}.md)"))
        rows_zh.append((f"`train {page.slug}`", page.summary_zh, f"[打开]({page.slug}.md)"))

    overview_en = f"""# CLI reference

The CLI is organized around two ideas:

- top-level workflow commands for running, resuming, inspecting, and scheduling jobs
- resource management commands for hosts, storage, secrets, and cloud providers

Start with [Quicktour](../quicktour.md) if you want a task-oriented path through the product. Use this section when you need exact command syntax.

## Command index

{markdown_table(("Command", "Purpose", "Page"), rows_en)}
"""
    overview_zh = f"""# CLI 参考

CLI 围绕两类能力组织：

- 顶层工作流命令，用来运行、恢复、查看和调度任务
- 资源管理命令，用来管理主机、存储、密钥和云资源

如果你想先按任务路径快速上手，请先看 [快速浏览](../quicktour.md)。当你需要精确的命令语法时，再使用这一节。

## 命令索引

{markdown_table(("命令", "用途", "页面"), rows_zh)}
"""
    write_localized_text(cli_dir / "_index.md", overview_en, overview_zh)


def render_method_section(name: str, member: object, *, fallback_summary: str, parameters_label: str, returns_label: str) -> str:
    summary = summarize_doc(member) or fallback_summary
    return (
        f"### `{name}`\n\n"
        f"```python\n{format_signature(name, member)}\n```\n\n"
        f"{summary}\n\n"
        f"**{parameters_label}**\n\n"
        f"{parameter_table(member)}\n\n"
        f"**{returns_label}**\n\n"
        f"{return_value(member)}"
    )


def generate_package_reference(docs_dir: Path) -> None:
    package_dir = docs_dir / "package-reference"
    index_rows_en: list[tuple[str, ...]] = []
    index_rows_zh: list[tuple[str, ...]] = []

    for page in API_PAGES:
        methods = list(page.members) if page.members else public_methods(page.cls) if page.cls is not None else []
        method_rows_en = [
            (
                f"`{name}`",
                f"`{format_signature(name, member)}`",
                summarize_doc(member) or "Public helper in this page.",
            )
            for name, member in methods
        ]
        method_rows_zh = [
            (
                f"`{name}`",
                f"`{format_signature(name, member)}`",
                summarize_doc(member) or "此页公开的 API helper。",
            )
            for name, member in methods
        ]
        scenarios_en = "\n".join(f"- {item}" for item in page.scenarios)
        scenarios_zh = "\n".join(f"- {item}" for item in page.scenarios_zh)
        reference_en = "\n\n".join(
            render_method_section(
                name,
                member,
                fallback_summary="Public helper exposed by this API page.",
                parameters_label="Parameters",
                returns_label="Returns",
            )
            for name, member in methods
        )
        reference_zh = "\n\n".join(
            render_method_section(
                name,
                member,
                fallback_summary="此页面公开的 API helper。",
                parameters_label="参数",
                returns_label="返回值",
            )
            for name, member in methods
        )
        content_en = f"""# {page.title}

## What this page covers

{page.description}

## Typical use cases

{scenarios_en}

## Entry point

```python
{page.builder}
```

## Common usage

```python
{page.usage}
```

## API summary

{markdown_table(("Helper", "Signature", "Purpose"), method_rows_en)}

## Detailed reference

{reference_en}
"""
        content_zh = f"""# {page.title_zh}

## 本页说明

{page.description_zh}

## 典型使用场景

{scenarios_zh}

## 入口

```python
{page.builder}
```

## 常见用法

```python
{page.usage}
```

## API 概览

{markdown_table(("Helper", "签名", "用途"), method_rows_zh)}

## 详细参考

{reference_zh}
"""
        write_localized_text(package_dir / f"{page.slug}.md", content_en, content_zh)
        index_rows_en.append((page.title, page.description, f"[Open]({page.slug}.md)"))
        index_rows_zh.append((page.title_zh, page.description_zh, f"[打开]({page.slug}.md)"))

    public_rows: list[tuple[str, ...]] = []
    public_rows_zh: list[tuple[str, ...]] = []
    sections_en: list[str] = []
    sections_zh: list[str] = []
    for obj in PUBLIC_OBJECTS:
        if inspect.isclass(obj.member):
            signature = getattr(obj.member, "__name__", obj.name)
        else:
            signature = format_signature(obj.name, obj.member)
        public_rows.append((f"`{obj.name}`", f"`{signature}`", obj.summary))
        public_rows_zh.append((f"`{obj.name}`", f"`{signature}`", obj.summary_zh))
        sections_en.append(
            f"""## `{obj.name}`

{obj.summary}

```python
{signature}
```"""
        )
        sections_zh.append(
            f"""## `{obj.name}`

{obj.summary_zh}

```python
{signature}
```"""
        )
    write_localized_text(
        package_dir / "public-models.md",
        f"""# Public models and entry points

These are the public objects that appear in user-facing imports and runtime integrations.

## Summary

{markdown_table(("Object", "Signature", "Role"), public_rows)}

## Details

{'\n\n'.join(sections_en)}
""",
        f"""# 公共模型与入口

这些对象会出现在面向用户的导入路径和运行时集成中。

## 概览

{markdown_table(("对象", "签名", "角色"), public_rows_zh)}

## 详情

{'\n\n'.join(sections_zh)}
""",
    )

    overview_en = f"""# Package reference

This section is the technical reference for the Python authoring API exposed by:

```python
from trainsh.pyrecipe import *
```

Use it when you already understand the product shape and need exact top-level helper names, parameter names, or return types.

## Reference map

{markdown_table(("Page", "Focus", "Link"), index_rows_en + [("Public models", "Factory functions and exported model objects.", "[Open](public-models.md)")])}
"""
    overview_zh = f"""# Package Reference

这一节是 Python 编写 API 的技术参考，对应公开入口：

```python
from trainsh.pyrecipe import *
```

当你已经理解产品结构，只是需要查具体顶层 helper、参数名或返回类型时，请从这里开始。

## 参考地图

{markdown_table(("页面", "关注点", "链接"), index_rows_zh + [("公共模型", "工厂函数和导出的模型对象。", "[打开](public-models.md)")])}
"""
    write_localized_text(package_dir / "_index.md", overview_en, overview_zh)


def load_example_name(path: Path) -> str:
    try:
        loaded = load_python_recipe(path)
    except Exception:
        return path.stem
    return getattr(loaded, "name", path.stem)


def generate_examples(docs_dir: Path) -> None:
    examples_dir = docs_dir / "examples"
    source_dir = ROOT / "trainsh" / "examples"
    rows_en: list[tuple[str, ...]] = []
    rows_zh: list[tuple[str, ...]] = []

    for path in sorted(source_dir.glob("*.py")):
        recipe_name = load_example_name(path)
        summary = EXAMPLE_SUMMARIES.get(path.name, "Bundled trainsh example.")
        summary_zh = EXAMPLE_SUMMARIES_ZH.get(path.name, "trainsh 内置示例。")
        slug = path.stem
        source = path.read_text(encoding="utf-8").strip()
        write_localized_text(
            examples_dir / f"{slug}.md",
            f"""# {path.name}

{summary}

## Recipe name

```text
{recipe_name}
```

## Show this example

```bash
train recipes show {slug}
```

## Run this example

```bash
train run {recipe_name}
```

## Source

```python
{source}
```
""",
            f"""# {path.name}

{summary_zh}

## Recipe 名称

```text
{recipe_name}
```

## 查看这个示例

```bash
train recipes show {slug}
```

## 运行这个示例

```bash
train run {recipe_name}
```

## 源码

```python
{source}
```
""",
        )
        rows_en.append((path.name, summary, f"[Open]({slug}.md)"))
        rows_zh.append((path.name, summary_zh, f"[打开]({slug}.md)"))

    write_localized_text(
        examples_dir / "_index.md",
        f"""# Examples

These examples are real Python recipes bundled with trainsh. They are the bridge between tutorials and the package reference.

## Example index

{markdown_table(("Example", "What it demonstrates", "Page"), rows_en)}
""",
        f"""# 示例

这些示例都是真实随 trainsh 一起发布的 Python recipe，位于教程和 package reference 之间，适合作为完整范例阅读。

## 示例索引

{markdown_table(("示例", "说明", "页面"), rows_zh)}
""",
    )


def write_documentation_page(docs_dir: Path) -> None:
    write_localized_text(
        docs_dir / "documentation.md",
        """# Documentation System

The `trainsh` documentation site combines hand-written guides with generated reference material.

## Generated sections

- `docs/cli-reference/*.md`: generated from the real `train` help output
- `docs/package-reference/*.md`: generated from the public `trainsh.pyrecipe` API surface
- `docs/examples/*.md`: generated from bundled example recipes

Generate or refresh those pages with:

```bash
python scripts/generate_docs.py
```

To export the full Hugo docs tree into another site:

```bash
python scripts/generate_docs.py --output ~/Projects/Personal/trainsh-home/content/docs
```

## Hand-written sections

- `docs/_index.md`
- `docs/installation.md`
- `docs/quicktour.md`
- `docs/getting-started.md`
- `docs/tutorials/*`
- `docs/guides/*`
- `docs/concepts/*`
- `docs/python-recipes.md`
- `docs/recipe-design.md`
- `docs/storage-design.md`
- `docs/secrets.md`

These pages explain workflows, mental models, migration guidance, and architecture that cannot be generated from signatures alone.

## Integration target

The generated tree is intended for a Hugo site. The primary consumer is `trainsh-home`, where these pages live under `/docs/`.
""",
        """# 文档系统

`trainsh` 文档站由手写指南和自动生成的参考页面共同组成。

## 自动生成的部分

- `docs/cli-reference/*.md`：从真实 `train` 帮助输出生成
- `docs/package-reference/*.md`：从公开 `trainsh.pyrecipe` API 自动提取
- `docs/examples/*.md`：从内置示例 recipe 自动生成

生成或刷新这些页面：

```bash
python scripts/generate_docs.py
```

把完整 Hugo 文档树导出到另一个站点：

```bash
python scripts/generate_docs.py --output ~/Projects/Personal/trainsh-home/content/docs
```

## 手写页面

- `docs/_index.md`
- `docs/installation.md`
- `docs/quicktour.md`
- `docs/getting-started.md`
- `docs/tutorials/*`
- `docs/guides/*`
- `docs/concepts/*`
- `docs/python-recipes.md`
- `docs/recipe-design.md`
- `docs/storage-design.md`
- `docs/secrets.md`

这些页面用于解释工作流、心智模型、迁移建议和无法仅靠函数签名生成的架构信息。

## 集成目标

生成出来的树面向 Hugo 站点。当前主要消费方是 `trainsh-home`，这些页面会挂在 `/docs/` 下。
""",
    )


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    source_docs_dir = SOURCE_DOCS_DIR.resolve()
    output_dir = args.output.resolve()
    source_docs_dir.mkdir(parents=True, exist_ok=True)
    reset_generated_dirs(source_docs_dir)

    with tempfile.TemporaryDirectory(prefix="trainsh-docs-home-") as temp_home:
        home = Path(temp_home)
        generate_cli_reference(source_docs_dir, home)
        generate_package_reference(source_docs_dir)
        generate_examples(source_docs_dir)
        write_documentation_page(source_docs_dir)

    if output_dir != source_docs_dir:
        export_hugo_tree(source_docs_dir, output_dir)
    print(f"Generated documentation under {source_docs_dir}")
    if output_dir != source_docs_dir:
        print(f"Exported Hugo documentation to {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
