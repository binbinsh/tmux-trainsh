from pathlib import Path
from textwrap import dedent

from trainsh import Host, Recipe


recipe = Recipe(
    "nanochat",
    owner="ml",
    tags=["bundle", "vast", "nanochat"],
    executor="thread_pool",
    workers=4,
    callbacks=["console", "sqlite"],
)

gpu = Host("placeholder", name="gpu")
repo_url = "https://github.com/karpathy/nanochat.git"
repo_dir = "/workspace/nanochat"
remote_script = f"{repo_dir}/runs/trainsh_nanochat.sh"
remote_data_dir = "/workspace/nanochat-data"
local_output = Path("./nanochat-output")
preferred_image = "pytorch/pytorch:latest"
disk_gb = 200
model_tag = "trainsh-nanochat"


runner_body = dedent(
    f"""\
    #!/usr/bin/env bash
    set -euo pipefail

    export OMP_NUM_THREADS=1
    export NANOCHAT_BASE_DIR={remote_data_dir}
    export PATH="$HOME/.local/bin:$PATH"
    export NANOCHAT_MODEL_TAG={model_tag}
    mkdir -p "$NANOCHAT_BASE_DIR"
    rm -f "$NANOCHAT_BASE_DIR/trainsh_success.txt"

    cd {repo_dir}
    . .venv/bin/activate

    if [ ! -e /usr/lib/x86_64-linux-gnu/libcuda.so ] && [ -e /usr/lib/x86_64-linux-gnu/libcuda.so.1 ]; then
      ln -s /usr/lib/x86_64-linux-gnu/libcuda.so.1 /usr/lib/x86_64-linux-gnu/libcuda.so
    fi
    if [ ! -e /lib/x86_64-linux-gnu/libcuda.so ] && [ -e /lib/x86_64-linux-gnu/libcuda.so.1 ]; then
      ln -s /lib/x86_64-linux-gnu/libcuda.so.1 /lib/x86_64-linux-gnu/libcuda.so
    fi

    if [ -z "${{WANDB_RUN:-}}" ]; then
      export WANDB_RUN=dummy
    fi
    export WANDB_MODE=disabled

    latest_checkpoint_step() {{
      python - "$1" <<'PY'
    import glob
    import os
    import re
    import sys

    checkpoint_dir = sys.argv[1]
    steps = []
    for path in glob.glob(os.path.join(checkpoint_dir, "model_*.pt")):
        match = re.search(r"model_(\\d+)\\.pt$", os.path.basename(path))
        if match:
            steps.append(int(match.group(1)))
    print(max(steps) if steps else "")
    PY
    }}

    python -m nanochat.report reset

    python -m nanochat.dataset -n 8
    python -m nanochat.dataset -n 170 &
    DATASET_DOWNLOAD_PID=$!

    python -m scripts.tok_train
    python -m scripts.tok_eval

    wait "$DATASET_DOWNLOAD_PID"

    BASE_CHECKPOINT_DIR="$NANOCHAT_BASE_DIR/base_checkpoints/$NANOCHAT_MODEL_TAG"
    BASE_RESUME_STEP="$(latest_checkpoint_step "$BASE_CHECKPOINT_DIR")"

    if [ -n "$BASE_RESUME_STEP" ]; then
      echo "Resuming base_train from step $BASE_RESUME_STEP"
      torchrun --standalone --nproc_per_node=8 -m scripts.base_train -- --depth=24 --target-param-data-ratio=9.5 --device-batch-size=16 --fp8 --run="$WANDB_RUN" --model-tag="$NANOCHAT_MODEL_TAG" --save-every=2000 --resume-from-step="$BASE_RESUME_STEP"
    else
      torchrun --standalone --nproc_per_node=8 -m scripts.base_train -- --depth=24 --target-param-data-ratio=9.5 --device-batch-size=16 --fp8 --run="$WANDB_RUN" --model-tag="$NANOCHAT_MODEL_TAG" --save-every=2000
    fi
    torchrun --standalone --nproc_per_node=8 -m scripts.base_eval -- --device-batch-size=16 --model-tag="$NANOCHAT_MODEL_TAG"

    curl -L -o "$NANOCHAT_BASE_DIR/identity_conversations.jsonl" https://karpathy-public.s3.us-west-2.amazonaws.com/identity_conversations.jsonl

    torchrun --standalone --nproc_per_node=8 -m scripts.chat_sft -- --device-batch-size=16 --run="$WANDB_RUN" --model-tag="$NANOCHAT_MODEL_TAG"
    torchrun --standalone --nproc_per_node=8 -m scripts.chat_eval -- -i sft -g "$NANOCHAT_MODEL_TAG"

    python -m nanochat.report generate
    printf 'ok\\n' > "$NANOCHAT_BASE_DIR/trainsh_success.txt"
    """
)


# Vast provisioning: prefer 8xH200, fall back to 8xH100.
h200 = recipe.vast.pick(
    host="gpu",
    gpu_name="H200",
    num_gpus=8,
    min_gpu_ram=80,
    limit=10,
    auto_select=True,
    create_if_missing=True,
    image=preferred_image,
    disk_gb=disk_gb,
    id="pick_h200",
    step_options={"continue_on_failure": True},
)
h100 = recipe.vast.pick(
    host="gpu",
    gpu_name="H100",
    num_gpus=8,
    min_gpu_ram=80,
    limit=10,
    auto_select=True,
    create_if_missing=True,
    image=preferred_image,
    disk_gb=disk_gb,
    id="pick_h100",
    depends_on=[h200],
    step_options={"trigger_rule": "all_failed"},
)
picked_gpu = recipe.on_one_success(id="picked_gpu", depends_on=[h200, h100])
start_instance = recipe.vast.start(id="start_instance", depends_on=[picked_gpu])
wait_ready = recipe.vast.wait_ready(timeout="30m", id="wait_ready", depends_on=[start_instance])


# Remote workspace bootstrap: clone repo, install uv, create the venv, and write a runner.
with recipe.linear():
    work = recipe.session("work", host=gpu, id="open_work", depends_on=[wait_ready])
    work.run(
        f"git clone {repo_url} {repo_dir} 2>/dev/null || (cd {repo_dir} && git pull --ff-only)",
        id="clone_repo",
    )
    work.install_uv(id="install_uv")
    work.run(
        "bash -lc '"
        "set -euo pipefail; "
        f"export PATH=\"$HOME/.local/bin:$PATH\"; "
        "if command -v apt-get >/dev/null 2>&1; then apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y build-essential; fi; "
        f"mkdir -p {remote_data_dir}; "
        f"cd {repo_dir}; "
        "if [ ! -e /usr/lib/x86_64-linux-gnu/libcuda.so ] && [ -e /usr/lib/x86_64-linux-gnu/libcuda.so.1 ]; then ln -s /usr/lib/x86_64-linux-gnu/libcuda.so.1 /usr/lib/x86_64-linux-gnu/libcuda.so; fi; "
        "if [ ! -e /lib/x86_64-linux-gnu/libcuda.so ] && [ -e /lib/x86_64-linux-gnu/libcuda.so.1 ]; then ln -s /lib/x86_64-linux-gnu/libcuda.so.1 /lib/x86_64-linux-gnu/libcuda.so; fi; "
        "if [ ! -d .venv ]; then uv venv; fi; "
        ". .venv/bin/activate; "
        "uv sync --extra gpu; "
        "uv pip install wandb"
        "'",
        id="prepare_runtime",
    )
    work.run(
        f"""cat > {remote_script} <<'SCRIPT'
{runner_body.rstrip()}
SCRIPT
chmod +x {remote_script}""",
        id="write_runner",
    )
    work.run(
        f"bash {remote_script} 2>&1 | tee {remote_data_dir}/nanochat.log",
        background=True,
        id="run_nanochat",
    )
    work.file(
        f"{remote_data_dir}/trainsh_success.txt",
        timeout="10h",
        id="wait_success_flag",
    )


# Artifact copy-back: checkpoints, report, logs, and success marker.
copy_base = recipe.copy(
    gpu.path(f"{remote_data_dir}/base_checkpoints"),
    local_output / "base_checkpoints",
    id="copy_base_checkpoints",
    depends_on=["wait_success_flag"],
)
copy_sft = recipe.copy(
    gpu.path(f"{remote_data_dir}/chatsft_checkpoints"),
    local_output / "chatsft_checkpoints",
    id="copy_sft_checkpoints",
    depends_on=[copy_base],
)
copy_report = recipe.copy(
    gpu.path(f"{remote_data_dir}/report"),
    local_output / "report",
    id="copy_report",
    depends_on=[copy_sft],
)
copy_log = recipe.copy(
    gpu.path(f"{remote_data_dir}/nanochat.log"),
    local_output / "nanochat.log",
    id="copy_nanochat_log",
    depends_on=[copy_report],
)
copy_success_flag = recipe.copy(
    gpu.path(f"{remote_data_dir}/trainsh_success.txt"),
    local_output / "trainsh_success.txt",
    id="copy_success_flag",
    depends_on=[copy_log],
)


# Cleanup and local verification: always close tmux and stop the Vast host.
cleanup_gate = recipe.join(id="cleanup_gate", depends_on=[copy_success_flag])
work.close(id="close_work", depends_on=[cleanup_gate])
recipe.vast.stop(id="stop_instance", depends_on=[cleanup_gate])

verify_report = recipe.assert_(
    f"file_exists:{local_output / 'report' / 'report.md'}",
    host="local",
    message="nanochat report was not copied locally",
    id="verify_report",
    depends_on=[cleanup_gate],
)
verify_base_ckpt = recipe.assert_(
    f"file_exists:{local_output / 'base_checkpoints'}",
    host="local",
    message="nanochat base checkpoints were not copied locally",
    id="verify_base_ckpt",
    depends_on=[verify_report],
)
verify_sft_ckpt = recipe.assert_(
    f"file_exists:{local_output / 'chatsft_checkpoints'}",
    host="local",
    message="nanochat chatsft checkpoints were not copied locally",
    id="verify_sft_ckpt",
    depends_on=[verify_base_ckpt],
)
verify_success_flag = recipe.assert_(
    f"file_contains:{local_output / 'trainsh_success.txt'}:ok",
    host="local",
    message="nanochat training/eval success flag was not copied locally",
    id="verify_success_flag",
    depends_on=[verify_sft_ckpt],
)
recipe.notify(
    "nanochat training, eval, copy-back, and shutdown completed",
    id="notify_complete",
    depends_on=[verify_success_flag],
)
