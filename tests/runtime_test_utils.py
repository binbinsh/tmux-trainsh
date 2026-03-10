import tempfile
from contextlib import ExitStack, contextmanager
from pathlib import Path
from typing import Any, Iterator
from unittest.mock import patch

from trainsh.core.executor_main import DSLExecutor


@contextmanager
def isolated_executor(
    recipe_model: Any,
    *,
    executor_name: str = "sequential",
    executor_kwargs: dict[str, Any] | None = None,
) -> Iterator[tuple[DSLExecutor, Path]]:
    with tempfile.TemporaryDirectory() as tmpdir, ExitStack() as stack:
        config_dir = Path(tmpdir) / "config"
        jobs_dir = config_dir / "jobs"
        jobs_dir.mkdir(parents=True, exist_ok=True)

        stack.enter_context(
            patch(
                "trainsh.core.executor_main.load_config",
                return_value={"tmux": {"auto_bridge": False}},
            )
        )
        stack.enter_context(patch("trainsh.core.executor_main.CONFIG_DIR", config_dir))
        stack.enter_context(patch("trainsh.runtime.CONFIG_DIR", config_dir))
        stack.enter_context(patch("trainsh.core.job_state.JOBS_DIR", jobs_dir))
        stack.enter_context(patch("trainsh.core.execution_log.JOBS_DIR", jobs_dir))
        stack.enter_context(patch("trainsh.commands.storage.load_storages", return_value={}))

        executor = DSLExecutor(
            recipe_model,
            log_callback=lambda *_args, **_kwargs: None,
            executor_name=executor_name,
            executor_kwargs=executor_kwargs or {},
        )
        yield executor, config_dir
