# AGENTS

Versioning rule:

- Project versions use `YY.MMDD.HHMM`.
- `YY` is the two-digit year.
- `MMDD` is month and day.
- `HHMM` is 24-hour time.
- Example: `26.0310.1845` means 2026-03-10 18:45.

Project-level constraints for `pyrecipe` migration work:

- Keep the Python recipe runtime split across multiple files; do not collapse everything into one module.
- Any new or refactored Python implementation file should be kept under 800 lines.
- New `trainsh/pyrecipe` API modules:
  - `trainsh/pyrecipe/__init__.py`
  - `trainsh/pyrecipe/base.py`
  - `trainsh/pyrecipe/models.py`
  - `trainsh/pyrecipe/provider_steps.py`
  - `trainsh/pyrecipe/provider_condition_steps.py`
  - `trainsh/pyrecipe/provider_misc_steps.py`
  - `trainsh/pyrecipe/storage_steps.py`
  - `trainsh/pyrecipe/control_steps.py`
  - `trainsh/pyrecipe/loader.py`
- Existing users should keep using `from trainsh.pyrecipe import recipe, load_python_recipe`.
- For `.py` recipes, execution should remain: load → schedule by `depends_on` → run with configured executor (`sequential`/`thread_pool`).
- Keep Python runtime modules small; each pyrecipe API module stays under 800 lines.
- Additional migration status:
  - Keep Airflow-like retry/timeout semantics and execute-time scheduling in the new Python runtime.
- `execution_timeout` and `retry_exponential_backoff` are now supported on Python recipe steps.
- Added step-level callback support (`on_success` / `on_failure`) for `.py` recipe steps, including callables and callback forms (command/provider).
- Added explicit fail/probe helpers (`util.fail`) and trigger-rule join helpers (`on_all_success`, `on_all_failed`, etc.).
- Provider/control helper APIs keep being expanded with simple aliases (`bash`, `python`, `empty/noop`, `notify`, `vast.*`) while preserving simplicity.
- Added a dedicated SQLite provider for `.py` recipes (`sqlite_query`, `sqlite_exec`, `sqlite_script`) plus runtime handlers for query/select/execute/script operations.
- Fixed HTTP runtime handler duplication and kept the enhanced implementation with robust status-aware request/wait behavior as the active one.
- Executor compatibility progress: `sequential`, `thread_pool`, `process_pool`, `local`, `airflow`, `celery`, `dask`, and `debug` executor aliases are supported. `thread_pool`-style execution is used for dependency scheduling and pool-based step throttling.
- Kubernetes executor alias is intentionally unsupported in this runtime and now returns an explicit unsupported error path.
- Latest migration progress:
  - Added Python runtime entry points for Airflow-like branching control: `wait_condition`, `branch`, `short_circuit`, `skip_if`, `skip_if_not`.
  - Added `latest_only` control helper (via `util.latest_only`) to skip non-latest runs when sqlite runtime history is available.
  - Added Python runtime `storage_wait` family (`storage_wait`, `storage_wait_for`, `storage_wait_for_key`) with polling timeout support.
  - Added `join(...)` control helper defaulting to `trigger_rule="all_done"` for branch merge points.
  - Split conditional provider helpers into `trainsh/pyrecipe/provider_condition_steps.py` to keep file size manageable and avoid monolithic `pyrecipe` modules.
- Added `.py` HTTP provider support beyond `http_request`: direct method aliases (`http_get`, `http_post`, `http_put`, `http_delete`, `http_head`) plus `http_wait_for_status`/`http_wait`.
- Added `.py` HTTP aliases for Airflow-style sensor naming (`http_sensor`) and JSON helper (`http_request_json`).
- Added `.py` provider aliases (`email`, `ssh`) and provider-name compatibility aliases (`email`, `mail`, `notify`) in runtime dispatch.
- Added operator-style helpers (`bash_operator`, `python_operator`, `http_operator`, `sql_operator`, `cloud_operator`) in `trainsh/pyrecipe/provider_operator_steps.py`.
- Added additional Airflow-like operator helpers in `provider_operator_steps` (`branch_operator`, `short_circuit_operator`, and common notification operator aliases).
- Extended runtime provider dispatch with Airflow-flavored operator aliases for these operators:
  - `bash`/`python` (`bash`, `local_run` style and operation aliases)
  - `http` operation aliases (`http`, `json` helpers, `http` wait variants)
  - `sql` operation aliases (`db` provider, `get_records`, `write`, etc.)
  - `cloud` provider mapped to storage family for upload/download/list/exists/read/info/mkdir/delete/wait/rename.
- Updated Python runtime to route airflow/Celery/local-style executor names through dependency-based parallel scheduling (`depends_on` + pools) in `.run` (without Kubernetes).
- Expanded runtime executor resolution with more Airflow compatibility aliases (`airflow`, `celery`, `dask`, legacy/local executor variants) and normalized argument parsing (`--workers`, `--concurrency`).
- Added `defaults(max_retries=...)` as an alias to Airflow-style retries configuration.
- Added Airflow-oriented provider aliases for runtime dispatch (`httpx`/`requests`, `cp` transfer op, storage op aliases like `ls`/`test`/`check`, and extra notification providers via webhook/slack/telegram/discord/opsgenie/pagerduty-style names).
- Extended `.py` recipe mixins with webhook/Slack/Telegram/Discord/Email entrypoints and storage copy/move/sync/mirror/remove aliases for clearer migration from airflow storage/provider task patterns.
- Extended runtime sqlite metadata persistence to write `dag`, `dag_run`, and `task_instance` rows on execution lifecycle events, plus `latest_only` fallback/query compatibility via `dag_run` and legacy `recipe_runs` tables.
- Added Python-side DAG core modules (not replacing the old DSL path): `core/dag_processor.py`, `core/dag_executor.py`, `core/scheduler.py`.
- Added new exports in `core/__init__.py` so external code can directly consume:
  - `DagProcessor`
  - `DagExecutor`
  - `DagScheduler`
- Added lightweight Airflow-like XCom support on sqlite runtime metadata:
  - new `xcom` table persistence in callback runtime
  - provider/runtime ops: `util.xcom_push`, `util.xcom_pull` (plus `xcom.push`, `xcom.pull`)
  - py recipe helpers: `xcom_push`, `xcom_pull`, `xcom_push_operator`, `xcom_pull_operator`
  - `try_number` is now propagated in step callback events and persisted to `task_instance.try_number`.
- Runtime executor alias/compatibility definitions were split into `trainsh/runtime_executors.py` to keep module size constraints.
