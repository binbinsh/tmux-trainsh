"""Recipe file templates used by the CLI."""

from __future__ import annotations

from textwrap import dedent


_MINIMAL_TEMPLATE = """\
from trainsh.pyrecipe import *

recipe("__NAME__", schedule="@every 30m", callbacks=["console", "sqlite"])
var("MESSAGE", "Hello from trainsh")

main = session("main", on="local")
hello = main('echo "$MESSAGE"')
noticed = notice("$MESSAGE", after=hello)
main.close(after=noticed)
"""


_FEATURE_TOUR_TEMPLATE = '''\
from trainsh.pyrecipe import *

recipe(
    "__NAME__",
    schedule="@every 30m",
    owner="ml",
    tags=["feature-tour", "python"],
    executor="thread_pool",
    workers=4,
    pools={
        "default": 4,
        "io": 2,
    },
    callbacks=["console", "sqlite"],
)

defaults(
    retry=1,
    retry_delay="5s",
    timeout="10m",
    backoff=True,
    trigger="all_success",
    pool="default",
)

var("HEALTHCHECK_URL", "https://example.com")
var("RUN_NAME", "demo-run")
var("RUN_MODE", "development")
var("SQLITE_DB", "./runtime-feature-tour.db")
storage("artifacts", "r2:your-bucket")

latest = latest_only(
    message="A newer run exists; skip this one.",
    fail_if_unknown=False,
    id="latest",
)
prepare_db = sql_script(
    """
    CREATE TABLE IF NOT EXISTS workflow_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        event TEXT NOT NULL,
        details TEXT NOT NULL
    );
    """,
    db="$SQLITE_DB",
    id="prepare_db",
    after=latest,
    pool="io",
)
health = http_wait(
    "$HEALTHCHECK_URL",
    status=200,
    timeout="2m",
    every="10s",
    capture="HEALTH_BODY",
    id="healthcheck",
    after=prepare_db,
    pool="io",
    execution_timeout="3m",
)
push_health = xcom_push(
    "health_payload",
    from_var="HEALTH_BODY",
    id="push_health",
    after=health,
)
choose_path = choose(
    "EXECUTION_PATH",
    when='RUN_MODE == "production"',
    then="production",
    else_="development",
    id="choose_path",
    after=push_health,
)

main = session("main", on="local", id="open_main", after=choose_path)
writer = main.bg(
    "sh -lc 'mkdir -p /tmp/trainsh-feature-tour && "
    "printf \\\"%s\\\\n\\\" \\\"$EXECUTION_PATH\\\" > /tmp/trainsh-feature-tour/mode.txt && "
    "sleep 1 && printf \\\"training finished\\\\n\\\" | tee /tmp/trainsh-feature-tour/done.txt'",
    id="writer",
    retry=2,
    retry_delay="15s",
    backoff=True,
    execution_timeout="15m",
    on_success=["echo callback success for {step_id}"],
    on_failure=["echo callback failure for {step_id}"],
)
seen_text = main.wait(
    "training finished",
    timeout="30s",
    id="seen_text",
    after=writer,
    pool="io",
)
idle = main.idle(
    timeout="2m",
    id="idle",
    after=seen_text,
    pool="io",
)
done_file = main.file(
    "/tmp/trainsh-feature-tour/done.txt",
    timeout="30s",
    id="done_file",
    after=idle,
    pool="io",
)
confirmed = wait_condition(
    "file_exists:/tmp/trainsh-feature-tour/done.txt",
    host="local",
    timeout="30s",
    id="confirmed",
    after=done_file,
    pool="io",
)
record_completion = sql_exec(
    "INSERT INTO workflow_events(event, details) VALUES ('session', 'done file observed')",
    db="$SQLITE_DB",
    id="record_completion",
    after=confirmed,
    pool="io",
)
optional_storage = storage_wait(
    "artifacts",
    "/runs/$RUN_NAME/ready.txt",
    timeout="30s",
    id="optional_storage",
    after=done_file,
    pool="io",
    continue_on_failure=True,
    trigger="all_done",
)
merge = join(
    id="merge",
    after=[record_completion, optional_storage],
)
pull_health = xcom_pull(
    "health_payload",
    task_ids=["push_health"],
    output_var="HEALTH_BODY_FROM_XCOM",
    id="pull_health",
    after=merge,
)
summary = sql_query(
    "SELECT event, details FROM workflow_events ORDER BY id DESC",
    db="$SQLITE_DB",
    into="RECENT_EVENTS",
    id="summary",
    after=pull_health,
    pool="io",
)
notice(
    "Feature tour completed for $RUN_NAME via $EXECUTION_PATH",
    channels=["log", "system"],
    id="done",
    after=summary,
)
main.close(after=summary)
'''


_TEMPLATES = {
    "minimal": _MINIMAL_TEMPLATE,
    "feature-tour": _FEATURE_TOUR_TEMPLATE,
    "full": _FEATURE_TOUR_TEMPLATE,
}


def list_template_names() -> list[str]:
    names = []
    for name in _TEMPLATES:
        if name not in names:
            names.append(name)
    return names


def get_recipe_template(template_name: str, recipe_name: str) -> str:
    key = str(template_name or "feature-tour").strip().lower() or "feature-tour"
    try:
        template = _TEMPLATES[key]
    except KeyError as exc:
        available = ", ".join(list_template_names())
        raise ValueError(f"Unknown template: {template_name}. Available: {available}") from exc
    return dedent(template).replace("__NAME__", recipe_name)


__all__ = ["get_recipe_template", "list_template_names"]
