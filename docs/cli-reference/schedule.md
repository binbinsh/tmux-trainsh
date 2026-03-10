# Schedule

Run and inspect timed recipes.

## When to use it

- List scheduled recipes.
- Run the scheduler once or as a long-lived service.

## Command

```bash
train schedule --help
```

## CLI help output

```text
Usage:
  train schedule [run] [--forever|--once] [--dag NAME] [--dags-dir PATH]
                 [--force] [--wait] [--include-invalid]
                 [--loop-interval N] [--max-active-runs N]
                 [--max-active-runs-per-dag N] [--iterations N]
                 [--sqlite-db PATH]
  train schedule list [--include-invalid] [--dags-dir PATH] [--sqlite-db PATH] [PATTERN...]
  train schedule status [--rows N] [--sqlite-db PATH]

Notes:
  --force: run all matched dags ignoring schedule
  --wait: when running, wait for started dags to finish
```
