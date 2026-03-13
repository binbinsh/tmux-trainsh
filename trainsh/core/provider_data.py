"""Data, pricing, sqlite, and xcom provider helpers."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
from contextlib import closing
from datetime import datetime
from typing import Any, Dict, List, Optional

from ..constants import CONFIG_DIR
from .models import Storage, StorageType
from .runtime_db import DEFAULT_XCOM_RETENTION_DAYS, ensure_xcom_schema, prune_old_xcom


class ExecutorProviderDataMixin:
    def _coerce_float(self, value: Any, *, default: float = 0.0) -> float:
        """Normalize float-like values."""
        if value is None:
            return default
        if isinstance(value, (int, float)):
            return float(value)
        try:
            return float(str(value).strip())
        except Exception:
            return default

    def _coerce_int(self, value: Any, *, default: int = 0) -> int:
        """Normalize int-like values."""
        if value is None:
            return default
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, int):
            return int(value)
        try:
            return int(str(value).strip())
        except Exception:
            return default

    def _resolve_storage(self, storage_name: Any) -> Optional[Storage]:
        """Resolve storage name to Storage object."""
        name = str(storage_name).strip() if storage_name is not None else ""
        if not name:
            return None
        return self._build_transfer_storages().get(name)

    def _storage_local_path(self, storage: Storage, path: str) -> str:
        """Resolve a path within local storage."""
        base_path = str(storage.config.get("path", "")).strip()
        relative = str(path or "").strip().lstrip("/")
        if base_path:
            if not relative:
                return os.path.expanduser(base_path)
            return os.path.join(os.path.expanduser(base_path), relative)
        return os.path.expanduser(relative or ".")

    def _storage_rclone_path(self, storage: Storage, path: str) -> str:
        """Resolve a path for rclone operations."""
        from ..services.transfer_engine import get_rclone_remote_name
        from ..services.transfer_support import resolve_storage_remote_path

        remote_name = get_rclone_remote_name(storage)
        path_text = resolve_storage_remote_path(storage, path)
        return f"{remote_name}:{path_text}"

    def _exec_storage_rclone(
        self,
        storage: Storage,
        args: List[str],
        *,
        timeout: int = 300,
    ) -> tuple[bool, str]:
        """Execute a storage command through rclone."""
        from ..services.transfer_engine import build_rclone_env, check_rclone_available

        if not check_rclone_available():
            return False, "rclone is required. Install with: brew install rclone"

        env = os.environ.copy()
        env.update(build_rclone_env(storage))
        try:
            result = subprocess.run(
                ["rclone", *args],
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
            )
        except FileNotFoundError:
            return False, "rclone command not found. Install with: brew install rclone"
        except subprocess.TimeoutExpired:
            return False, f"rclone command timed out after {timeout}s"
        except Exception as exc:
            return False, str(exc)

        output = (result.stdout or "").strip()
        error = (result.stderr or "").strip()
        message = output or error
        if result.returncode == 0:
            return True, message or "storage operation completed"
        return False, message or "storage operation failed"

    def _exec_provider_hf_download(self, params: Dict[str, Any]) -> tuple[bool, str]:
        """Download model files from HuggingFace."""
        if not isinstance(params, dict):
            return False, "Provider util.hf_download params must be an object"

        repo_id = self._interpolate(str(params.get("repo_id", ""))).strip()
        if not repo_id:
            return False, "Provider util.hf_download requires 'repo_id'"

        local_dir = self._interpolate(str(params.get("local_dir", ""))).strip()
        revision = self._interpolate(str(params.get("revision", ""))).strip()
        token = self._interpolate(str(params.get("token", ""))).strip()
        filename = self._interpolate(str(params.get("filename", ""))).strip()
        filenames = params.get("filenames")

        command = f"huggingface-cli download {shlex.quote(repo_id)}"
        if revision:
            command += f" --revision {shlex.quote(revision)}"
        if local_dir:
            command += f" --local-dir {shlex.quote(local_dir)}"
        if token:
            command += f" --token {shlex.quote(token)}"
        if filename:
            command += f" --filename {shlex.quote(filename)}"
        elif isinstance(filenames, (list, tuple, set)):
            for item in filenames:
                file_name = self._interpolate(str(item)).strip()
                if file_name:
                    command += f" --filename {shlex.quote(file_name)}"

        return self._exec_provider_shell(
            {
                "command": command,
                "host": self._provider_host(params.get("host", "local")),
            }
        )

    def _exec_provider_fetch_exchange_rates(self, params: Dict[str, Any]) -> tuple[bool, str]:
        """Fetch exchange rates from provider."""
        if not isinstance(params, dict):
            return False, "Provider util.fetch_exchange_rates params must be an object"

        from ..services.pricing import fetch_exchange_rates, load_pricing_settings, save_pricing_settings

        try:
            rates = fetch_exchange_rates()
            settings = load_pricing_settings()
            settings.exchange_rates = rates
            save_pricing_settings(settings)
            for currency, rate in rates.rates.items():
                self.ctx.variables[f"rate_{str(currency).lower()}"] = str(rate)
            self.ctx.variables["exchange_rate_base"] = rates.base
            self.ctx.variables["exchange_rate_updated_at"] = rates.updated_at
            return True, f"Fetched {len(rates.rates)} exchange rates"
        except Exception as exc:
            return False, str(exc)

    def _exec_provider_calculate_cost(self, params: Dict[str, Any]) -> tuple[bool, str]:
        """Estimate cost from provider config."""
        if not isinstance(params, dict):
            return False, "Provider util.calculate_cost params must be an object"

        from ..services.pricing import (
            calculate_host_cost,
            ensure_exchange_rates,
            format_currency,
            get_display_currency,
            load_pricing_settings,
        )
        try:
            from ..services.vast_api import get_vast_client
        except Exception:
            get_vast_client = None

        settings = load_pricing_settings()
        default_currency = get_display_currency()
        currency = str(params.get("currency", default_currency)).upper() or default_currency
        rates = ensure_exchange_rates([currency], settings=settings)
        is_vast = self._coerce_bool(params.get("vast", False), default=False)
        host_id = self._interpolate(str(params.get("host_id", ""))).strip()
        gpu_hourly_usd = self._coerce_float(params.get("gpu_hourly_usd", 0), default=0.0)
        storage_gb = self._coerce_float(params.get("storage_gb", 0), default=0.0)

        if is_vast:
            if get_vast_client is None:
                return False, "Vast client unavailable"
            try:
                client = get_vast_client()
                instances = client.list_instances()
            except Exception as exc:
                return False, f"Failed to list Vast instances: {exc}"

            total_per_hour = 0.0
            matched = 0
            for inst in instances:
                hourly = getattr(inst, "dph_total", 0.0)
                if not hourly:
                    continue
                cost = calculate_host_cost(
                    host_id=str(inst.id),
                    gpu_hourly_usd=float(hourly),
                    host_name=getattr(inst, "gpu_name", ""),
                    source="vast_api",
                )
                total_per_hour += cost.total_per_hour_usd
                matched += 1
                self.ctx.variables[f"vast_{inst.id}_cost_per_hour_usd"] = str(cost.total_per_hour_usd)

            if not matched:
                return False, "No active Vast instance found for calculate_cost"

            self.ctx.variables["total_cost_per_hour_usd"] = str(total_per_hour)
            self.ctx.variables["total_cost_per_day_usd"] = str(total_per_hour * 24)
            self.ctx.variables["total_cost_per_month_usd"] = str(total_per_hour * 24 * 30)
            converted = rates.convert(total_per_hour, "USD", currency)
            self.ctx.variables[f"total_cost_per_hour_{currency.lower()}"] = str(converted)
            return True, f"{format_currency(converted, currency)}/hr"

        if not host_id and gpu_hourly_usd <= 0:
            return False, "Provider util.calculate_cost requires 'host_id' or 'gpu_hourly_usd' when vast=False"

        cost = calculate_host_cost(
            host_id=host_id or "manual",
            gpu_hourly_usd=gpu_hourly_usd,
            storage_gb=storage_gb,
            host_name=host_id or "",
            source="manual",
        )
        converted = rates.convert(cost.total_per_hour_usd, "USD", currency)
        self.ctx.variables["host_cost_per_hour_usd"] = str(cost.total_per_hour_usd)
        self.ctx.variables["host_cost_per_day_usd"] = str(cost.total_per_day_usd)
        self.ctx.variables["host_cost_per_month_usd"] = str(cost.total_per_month_usd)
        self.ctx.variables[f"host_cost_per_hour_{currency.lower()}"] = str(converted)
        return True, f"{format_currency(converted, currency)}/hr"

    def _sqlite_db_path(self, database: Any) -> str:
        """Resolve SQLite database path used by sqlite provider."""
        raw_db = str(database).strip() if database is not None else ""
        if raw_db:
            return os.path.expanduser(raw_db)
        return str(CONFIG_DIR / "runtime.db")

    def _normalize_sqlite_bindings(self, bindings: Any) -> Any:
        """Normalize SQL bind parameters."""
        if bindings is None:
            return ()

        if isinstance(bindings, (list, tuple, dict)):
            return bindings

        if isinstance(bindings, str):
            text = bindings.strip()
            if not text:
                return ()
            try:
                parsed = json.loads(text)
            except Exception:
                return (text,)
            return self._normalize_sqlite_bindings(parsed)

        return (bindings,)

    def _runtime_dag_id(self) -> str:
        """Resolve dag_id used by runtime metadata tables."""
        path = str(self.recipe_path or "").strip()
        if path:
            return path
        name = str(getattr(self.recipe, "name", "")).strip()
        if name:
            return name
        return "unknown_dag"

    def _maybe_prune_old_xcom(self, conn: Any, db_path: str) -> int:
        """Prune stale XCom rows once per executor/database path."""
        seen = getattr(self, "_xcom_pruned_dbs", None)
        if not isinstance(seen, set):
            seen = set()
            setattr(self, "_xcom_pruned_dbs", seen)
        normalized = os.path.abspath(os.path.expanduser(db_path))
        if normalized in seen:
            return 0
        removed = prune_old_xcom(conn, retention_days=DEFAULT_XCOM_RETENTION_DAYS)
        seen.add(normalized)
        return removed

    def _exec_provider_xcom_push(self, params: Dict[str, Any]) -> tuple[bool, str]:
        """Push one value into runtime sqlite xcom table."""
        if not isinstance(params, dict):
            return False, "Provider util.xcom_push params must be an object"

        key = str(params.get("key", "")).strip()
        if not key:
            return False, "Provider util.xcom_push requires 'key'"

        source_var = str(params.get("from_var", params.get("var", ""))).strip()
        raw_value = params.get("value")
        if raw_value is None and source_var:
            raw_value = self.ctx.variables.get(source_var, params.get("default", ""))
        if raw_value is None:
            raw_value = params.get("default", "")

        if isinstance(raw_value, (dict, list)):
            value_text = json.dumps(raw_value, ensure_ascii=False)
        elif raw_value is None:
            value_text = ""
        else:
            value_text = str(raw_value)

        dag_id = str(params.get("dag_id", "")).strip() or self._runtime_dag_id()
        run_id = str(params.get("run_id", "")).strip() or self.ctx.job_id
        task_id = (
            str(params.get("task_id", "")).strip()
            or self._current_step_id()
            or "anonymous"
        )
        map_index = self._coerce_int(params.get("map_index", 0), default=0)
        db = self._sqlite_db_path(params.get("database", params.get("sqlite_db")))
        created_at = datetime.now().isoformat()
        execution_date = str(params.get("execution_date", created_at)).strip() or created_at

        import sqlite3

        try:
            with closing(sqlite3.connect(os.path.expanduser(db))) as conn:
                ensure_xcom_schema(conn)
                self._maybe_prune_old_xcom(conn, db)
                conn.execute(
                    """
                    INSERT INTO xcom (
                        dag_id, task_id, run_id, map_index, key, value, created_at, execution_date
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(dag_id, task_id, run_id, map_index, key) DO UPDATE SET
                        value=excluded.value,
                        created_at=excluded.created_at,
                        execution_date=excluded.execution_date
                    """,
                    (
                        dag_id,
                        task_id,
                        run_id,
                        map_index,
                        key,
                        value_text,
                        created_at,
                        execution_date,
                    ),
                )
                conn.commit()
        except Exception as exc:
            return False, f"xcom push failed: {exc}"

        output_var = params.get("output_var")
        if output_var:
            self.ctx.variables[str(output_var)] = value_text

        self._emit_event(
            "xcom_push",
            step_num=self._current_step_num() or None,
            step_id=task_id,
            task_id=task_id,
            dag_id=dag_id,
            run_id=run_id,
            key=key,
            value=value_text,
            map_index=map_index,
            execution_date=execution_date,
            try_number=self._current_try_number(),
        )
        return True, f"xcom pushed: key={key}, task_id={task_id}, run_id={run_id}"

    def _exec_provider_xcom_pull(self, params: Dict[str, Any]) -> tuple[bool, str]:
        """Pull one value from runtime sqlite xcom table."""
        if not isinstance(params, dict):
            return False, "Provider util.xcom_pull params must be an object"

        key = str(params.get("key", "")).strip()
        if not key:
            return False, "Provider util.xcom_pull requires 'key'"

        dag_id = str(params.get("dag_id", "")).strip() or self._runtime_dag_id()
        run_id = str(params.get("run_id", "")).strip() or self.ctx.job_id
        include_prior_dates = self._coerce_bool(
            params.get("include_prior_dates", False),
            default=False,
        )
        db = self._sqlite_db_path(params.get("database", params.get("sqlite_db")))

        task_ids_raw = params.get("task_ids", params.get("task_id"))
        task_ids: List[str] = []
        if task_ids_raw is not None:
            if isinstance(task_ids_raw, (list, tuple, set)):
                task_ids = [str(item).strip() for item in task_ids_raw if str(item).strip()]
            elif isinstance(task_ids_raw, str):
                task_ids = [item.strip() for item in task_ids_raw.split(",") if item.strip()]
            else:
                task_ids = [str(task_ids_raw).strip()]

        map_index_raw = params.get("map_index", None)
        use_map_index = map_index_raw is not None and str(map_index_raw).strip() != ""
        map_index = self._coerce_int(map_index_raw, default=0)

        import sqlite3

        row: Optional[Any] = None
        try:
            with closing(sqlite3.connect(os.path.expanduser(db))) as conn:
                ensure_xcom_schema(conn)
                conn.row_factory = sqlite3.Row
                query = "SELECT value, task_id, run_id FROM xcom WHERE dag_id = ? AND key = ?"
                query_params: List[Any] = [dag_id, key]
                if task_ids:
                    placeholders = ",".join(["?"] * len(task_ids))
                    query += f" AND task_id IN ({placeholders})"
                    query_params.extend(task_ids)
                if not include_prior_dates:
                    query += " AND run_id = ?"
                    query_params.append(run_id)
                if use_map_index:
                    query += " AND map_index = ?"
                    query_params.append(map_index)
                query += " ORDER BY created_at DESC LIMIT 1"
                row = conn.execute(query, query_params).fetchone()
        except Exception as exc:
            return False, f"xcom pull failed: {exc}"

        output_var = params.get("output_var")
        if row is None:
            default_value = params.get("default", None)
            if default_value is None:
                if output_var:
                    self.ctx.variables[str(output_var)] = ""
                return True, f"xcom not found for key={key}"
            if isinstance(default_value, (dict, list)):
                value_text = json.dumps(default_value, ensure_ascii=False)
            else:
                value_text = str(default_value)
            if output_var:
                self.ctx.variables[str(output_var)] = value_text
            return True, value_text

        value_text = str(row["value"] or "")
        decode_json = self._coerce_bool(
            params.get("decode_json", params.get("as_json", False)),
            default=False,
        )
        result_text = value_text
        if decode_json and value_text:
            try:
                parsed = json.loads(value_text)
                if isinstance(parsed, (dict, list)):
                    result_text = json.dumps(parsed, ensure_ascii=False)
                elif parsed is None:
                    result_text = ""
                else:
                    result_text = str(parsed)
            except Exception:
                result_text = value_text

        if output_var:
            self.ctx.variables[str(output_var)] = result_text
        return True, result_text

    def _exec_provider_sqlite_query(self, params: Dict[str, Any]) -> tuple[bool, str]:
        """Run a SQLite query and serialize results."""
        if not isinstance(params, dict):
            return False, "Provider sqlite.query params must be an object"

        query = str(params.get("sql", params.get("query", ""))).strip()
        if not query:
            return False, "Provider sqlite.query requires 'sql' or 'query'"

        db = self._sqlite_db_path(params.get("database"))
        mode = str(params.get("mode", "all")).strip().lower()
        bindings = self._normalize_sqlite_bindings(params.get("params"))
        output_var = params.get("output_var")

        import sqlite3

        try:
            with closing(sqlite3.connect(os.path.expanduser(db))) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute(query, bindings) if bindings else conn.execute(query)
                rows = cursor.fetchall()
        except Exception as exc:
            return False, f"sqlite query failed: {exc}"

        if mode in {"first", "one", "fetchone"}:
            if not rows:
                payload = None
            else:
                payload = dict(rows[0])
        elif mode in {"scalar", "value"}:
            if not rows or len(rows[0].keys()) == 0:
                payload = None
            else:
                payload = rows[0][0]
        else:
            payload = [dict(row) for row in rows]

        if output_var:
            if isinstance(payload, (dict, list)):
                self.ctx.variables[str(output_var)] = json.dumps(payload, ensure_ascii=False)
            else:
                self.ctx.variables[str(output_var)] = "" if payload is None else str(payload)

        if payload is None:
            return True, "sqlite query returned no rows"
        if isinstance(payload, (dict, list)):
            return True, json.dumps(payload, ensure_ascii=False)
        return True, str(payload)

    def _exec_provider_sqlite_exec(self, params: Dict[str, Any]) -> tuple[bool, str]:
        """Run write-like SQLite SQL."""
        if not isinstance(params, dict):
            return False, "Provider sqlite.exec params must be an object"

        sql = str(params.get("sql", params.get("query", ""))).strip()
        if not sql:
            return False, "Provider sqlite.exec requires 'sql' (or 'query')"

        db = self._sqlite_db_path(params.get("database"))
        bindings = self._normalize_sqlite_bindings(params.get("params"))
        output_var = params.get("output_var")

        import sqlite3

        try:
            with closing(sqlite3.connect(os.path.expanduser(db))) as conn:
                cursor = conn.execute(sql, bindings) if bindings else conn.execute(sql)
                conn.commit()
        except Exception as exc:
            return False, f"sqlite execute failed: {exc}"

        if output_var is not None:
            self.ctx.variables[str(output_var)] = str(getattr(cursor, "rowcount", 0))

        return True, f"sqlite execute ok: rowcount={getattr(cursor, 'rowcount', 0)}"

    def _exec_provider_sqlite_script(self, params: Dict[str, Any]) -> tuple[bool, str]:
        """Execute a multi-statement SQLite script."""
        if not isinstance(params, dict):
            return False, "Provider sqlite.script params must be an object"

        script = str(params.get("script", "")).strip()
        if not script:
            return False, "Provider sqlite.script requires 'script'"

        db = self._sqlite_db_path(params.get("database"))
        output_var = params.get("output_var")

        import sqlite3

        try:
            with closing(sqlite3.connect(os.path.expanduser(db))) as conn:
                conn.executescript(script)
                conn.commit()
        except Exception as exc:
            return False, f"sqlite script failed: {exc}"

        if output_var is not None:
            self.ctx.variables[str(output_var)] = "ok"

        return True, "sqlite script executed"
