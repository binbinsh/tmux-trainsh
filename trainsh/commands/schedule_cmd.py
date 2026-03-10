"""Recipe DAG scheduling command."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Sequence
import os
import sys

from ..constants import CONFIG_DIR
from ..core import DagRunState, DagScheduler
from ..core.dag_processor import DagProcessor


usage = """Usage:
  train schedule [run] [--forever|--once] [--dag NAME] [--dags-dir PATH]
                 [--force] [--wait] [--include-invalid]
                 [--loop-interval N] [--max-active-runs N]
                 [--max-active-runs-per-dag N] [--iterations N]
                 [--sqlite-db PATH]
  train schedule list [--include-invalid] [--dags-dir PATH] [--sqlite-db PATH] [PATTERN...]
  train schedule status [--rows N] [--sqlite-db PATH]
"""


def _to_int(raw: str, *, field: str, default: Optional[int] = None) -> int:
    try:
        value = int(raw)
    except ValueError:
        print(f"Invalid {field}: {raw!r}")
        raise SystemExit(1)
    if value < 1:
        print(f"{field} must be >= 1: {raw!r}")
        raise SystemExit(1)
    return value


def _parse_args(args: Sequence[str], *, default_mode: str = "run") -> Dict[str, object]:
    mode = default_mode
    i = 0

    if i < len(args) and args[i] in {"run", "list", "status", "help"}:
        mode = args[i]
        i += 1
    if mode == "help":
        return {"mode": "help"}

    options: Dict[str, object] = {
        "mode": mode,
        "filters": [],
        "dag_ids": [],
        "forever": False,
        "once": mode == "run",
        "force": False,
        "wait": False,
        "include_invalid": False,
        "loop_interval": 60,
        "iterations": None,
        "max_active_runs": 16,
        "max_active_runs_per_dag": 1,
        "dags_dir": None,
        "sqlite_db": str(CONFIG_DIR / "runtime.db"),
        "rows": 50,
    }
    filters: List[str] = []

    while i < len(args):
        arg = args[i]

        if arg == "--forever":
            options["forever"] = True
            options["once"] = False
            i += 1
            continue
        if arg == "--once":
            options["forever"] = False
            options["once"] = True
            i += 1
            continue
        if arg == "--force":
            options["force"] = True
            i += 1
            continue
        if arg == "--wait":
            options["wait"] = True
            i += 1
            continue
        if arg == "--include-invalid":
            options["include_invalid"] = True
            i += 1
            continue
        if arg == "--help":
            options["mode"] = "help"
            return options

        if arg.startswith("--dag="):
            options.setdefault("dag_ids", []).append(arg.split("=", 1)[1])
            i += 1
            continue
        if arg in {"-d", "--dag"}:
            if i + 1 >= len(args):
                print("Missing value for --dag")
                raise SystemExit(1)
            options.setdefault("dag_ids", []).append(args[i + 1])
            i += 2
            continue

        if arg.startswith("--dags-dir="):
            options["dags_dir"] = arg.split("=", 1)[1]
            i += 1
            continue
        if arg in {"--dags-dir", "--recipes-dir"}:
            if i + 1 >= len(args):
                print("Missing value for --dags-dir")
                raise SystemExit(1)
            options["dags_dir"] = args[i + 1]
            i += 2
            continue

        if arg.startswith("--sqlite-db="):
            options["sqlite_db"] = arg.split("=", 1)[1]
            i += 1
            continue
        if arg == "--sqlite-db":
            if i + 1 >= len(args):
                print("Missing value for --sqlite-db")
                raise SystemExit(1)
            options["sqlite_db"] = args[i + 1]
            i += 2
            continue

        if arg.startswith("--loop-interval="):
            options["loop_interval"] = _to_int(arg.split("=", 1)[1], field="--loop-interval")
            i += 1
            continue
        if arg == "--loop-interval":
            if i + 1 >= len(args):
                print("Missing value for --loop-interval")
                raise SystemExit(1)
            options["loop_interval"] = _to_int(args[i + 1], field="--loop-interval")
            i += 2
            continue

        if arg.startswith("--max-active-runs="):
            options["max_active_runs"] = _to_int(
                arg.split("=", 1)[1],
                field="--max-active-runs",
            )
            i += 1
            continue
        if arg == "--max-active-runs":
            if i + 1 >= len(args):
                print("Missing value for --max-active-runs")
                raise SystemExit(1)
            options["max_active_runs"] = _to_int(args[i + 1], field="--max-active-runs")
            i += 2
            continue

        if arg.startswith("--max-active-runs-per-dag="):
            options["max_active_runs_per_dag"] = _to_int(
                arg.split("=", 1)[1],
                field="--max-active-runs-per-dag",
            )
            i += 1
            continue
        if arg == "--max-active-runs-per-dag":
            if i + 1 >= len(args):
                print("Missing value for --max-active-runs-per-dag")
                raise SystemExit(1)
            options["max_active_runs_per_dag"] = _to_int(
                args[i + 1],
                field="--max-active-runs-per-dag",
            )
            i += 2
            continue

        if arg.startswith("--iterations="):
            options["iterations"] = _to_int(arg.split("=", 1)[1], field="--iterations")
            i += 1
            continue
        if arg == "--iterations":
            if i + 1 >= len(args):
                print("Missing value for --iterations")
                raise SystemExit(1)
            options["iterations"] = _to_int(args[i + 1], field="--iterations")
            i += 2
            continue

        if arg.startswith("--rows="):
            options["rows"] = _to_int(arg.split("=", 1)[1], field="--rows")
            i += 1
            continue
        if arg == "--rows":
            if i + 1 >= len(args):
                print("Missing value for --rows")
                raise SystemExit(1)
            options["rows"] = _to_int(args[i + 1], field="--rows")
            i += 2
            continue

        if arg.startswith("--"):
            print(f"Unknown flag: {arg}")
            _print_usage()
            raise SystemExit(1)

        filters.append(arg)
        i += 1

    options["filters"] = filters
    return options


def _print_usage() -> None:
    print(
        usage
        + """
Notes:
  --force: run all matched dags ignoring schedule
  --wait: when running, wait for started dags to finish"""
    )


def _matches(target: str, candidates: List[str]) -> bool:
    if not candidates:
        return True
    return any(candidate in target for candidate in candidates)


def _latest_state_for_dag(conn: sqlite3.Connection, dag_id: str) -> Optional[sqlite3.Row]:
    has_table = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='dag_run'"
    ).fetchone()
    if not has_table:
        return None
    return conn.execute(
        "SELECT run_id, state, start_date, end_date FROM dag_run WHERE dag_id=? ORDER BY start_date DESC LIMIT 1",
        (dag_id,),
    ).fetchone()


def _query_history(conn: sqlite3.Connection, rows: int) -> List[sqlite3.Row]:
    has_table = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='dag_run'"
    ).fetchone()
    if not has_table:
        return []
    return conn.execute(
        "SELECT dag_id, run_id, state, run_type, execution_date, start_date, end_date "
        "FROM dag_run ORDER BY start_date DESC LIMIT ?",
        (rows,),
    ).fetchall()


def _is_running_state(state: str) -> bool:
    return str(state).lower() == "running"


def cmd_schedule_list(args: Sequence[str]) -> None:
    parsed = _parse_args(args, default_mode="list")
    if parsed.get("mode") == "help":
        _print_usage()
        return
    dags_dir = parsed.get("dags_dir")
    processor = DagProcessor([str(dags_dir)] if dags_dir else None)
    dags = processor.discover_dags()
    filters = [str(item) for item in parsed.get("filters", [])]

    if not parsed.get("include_invalid"):
        dags = [dag for dag in dags if dag.is_valid and dag.load_error is None]

    if filters:
        dags = [dag for dag in dags if _matches(dag.dag_id, filters) or _matches(dag.recipe_name, filters)]

    if not dags:
        print("No DAGs found.")
        return

    sqlite_db = str(parsed.get("sqlite_db") or "").strip() or str(CONFIG_DIR / "runtime.db")
    conn = sqlite3.connect(sqlite_db)
    conn.row_factory = sqlite3.Row
    try:
        print("DAG_ID\tSCHEDULE\tSTATE\tLAST_RUN\tRUN_ID\tPATH")
        for dag in sorted(dags, key=lambda d: d.recipe_name):
            row = _latest_state_for_dag(conn, dag.dag_id)
            if row is None:
                state = "-"
                run_id = "-"
                last = "-"
            else:
                state = str(row["state"] or "-")
                run_id = str(row["run_id"] or "-")
                if row["start_date"]:
                    last = str(row["start_date"])
                else:
                    last = "-"
            print(
                f"{dag.dag_id}\t"
                f"{dag.schedule or '-'}\t"
                f"{state}\t"
                f"{last}\t"
                f"{run_id}\t"
                f"{dag.path}"
            )
    finally:
        conn.close()


def cmd_schedule_status(args: Sequence[str]) -> None:
    parsed = _parse_args(args, default_mode="status")
    if parsed.get("mode") == "help":
        _print_usage()
        return
    rows = int(parsed.get("rows", 50))
    sqlite_db = str(parsed.get("sqlite_db") or "").strip() or str(CONFIG_DIR / "runtime.db")

    if not os.path.exists(sqlite_db):
        print(f"No runtime db found: {sqlite_db}")
        return

    conn = sqlite3.connect(sqlite_db)
    conn.row_factory = sqlite3.Row
    try:
        history = _query_history(conn, rows=rows)
        if not history:
            print("No runs recorded.")
            return

        print("DAG_ID\tRUN_ID\tSTATE\tRUN_TYPE\tSTARTED")
        for row in history:
            started = row["start_date"] or "-"
            print(
                f"{row['dag_id']}\t"
                f"{row['run_id']}\t"
                f"{row['state']}\t"
                f"{row['run_type']}\t"
                f"{started}"
            )
        running_count = sum(1 for row in history if _is_running_state(str(row["state"])))
        if running_count:
            print(f"\nRunning: {running_count}")
    finally:
        conn.close()


def cmd_schedule_run(args: Sequence[str]) -> None:
    parsed = _parse_args(args, default_mode="run")
    if parsed.get("mode") == "help":
        _print_usage()
        return

    dags_dir = parsed.get("dags_dir")
    loop_interval = int(parsed.get("loop_interval", 60))
    max_active_runs = int(parsed.get("max_active_runs", 16))
    max_active_runs_per_dag = int(parsed.get("max_active_runs_per_dag", 1))
    force = bool(parsed.get("force"))
    wait = bool(parsed.get("wait"))
    include_invalid = bool(parsed.get("include_invalid"))
    filters = list(parsed.get("dag_ids") or [])
    positional = list(parsed.get("filters") or [])
    filters.extend(positional)
    sqlitedb = str(parsed.get("sqlite_db") or "").strip() or str(CONFIG_DIR / "runtime.db")
    iterations = parsed.get("iterations")
    if iterations is not None:
        iterations = int(iterations)

    scheduler = DagScheduler(
        dags_dir=dags_dir,
        max_active_runs=max_active_runs,
        max_active_runs_per_dag=max_active_runs_per_dag,
        sqlite_db=sqlitedb,
        loop_interval=loop_interval,
    )

    if parsed.get("forever"):
        scheduler.run_forever(
            force=force,
            dag_ids=filters or None,
            loop_interval=loop_interval,
            max_iterations=iterations,
            wait_completed=wait,
        )
        return

    records = scheduler.run_once(
        force=force,
        dag_ids=filters or None,
        wait=wait,
        include_invalid=include_invalid,
    )

    if not records:
        print("No DAG was started.")
        return

    if wait:
        failed = any(record.state in {DagRunState.FAILED, DagRunState.ERROR} for record in records)
        for record in records:
            print(f"{record.state}\t{record.dag_id}\t{record.run_id}\t{record.message}")
        if failed:
            raise SystemExit(1)
    else:
        for record in records:
            print(f"started\t{record.dag_id}\t{record.run_id}\t{record.message}")


def cmd_schedule(args: List[str]) -> None:
    parsed = _parse_args(args, default_mode="run")
    mode = str(parsed.get("mode", "run"))
    if mode == "help":
        _print_usage()
        return

    if mode == "list":
        cmd_schedule_list(args[1:] if args and args[0] == "list" else args)
        return
    if mode == "status":
        cmd_schedule_status(args[1:] if args and args[0] == "status" else args)
        return
    if mode == "run":
        cmd_schedule_run(args[1:] if args and args[0] == "run" else args)
        return

    # Fallback: first arg is probably a filter in run mode.
    cmd_schedule_run(args)


def main(args: Sequence[str]) -> None:
    """Entry point for the top-level schedule command."""
    if args and args[0] in {"-h", "--help", "help"}:
        _print_usage()
        return
    cmd_schedule(list(args))


if __name__ == "__main__":
    main(sys.argv[1:])
elif __name__ == "__doc__":
    cd = sys.cli_docs  # type: ignore
    cd["usage"] = usage
    cd["help_text"] = "Run and inspect scheduled Python recipes"
    cd["short_desc"] = "Scheduler operations"
