# Runtime metadata

`trainsh` persists workflow runtime state so that runs can be inspected and, in many cases, resumed.

## What is stored

The runtime metadata database records:

- DAG and run metadata
- task instance state
- try numbers
- XCom values

This metadata is also what powers `latest_only` and parts of the scheduler behavior.

## Why it matters

Runtime metadata enables:

- `train jobs`
- `train status`
- `train logs`
- `train resume <name>`

## Related pages

- [Schedule and resume runs](../tutorials/scheduling-and-resume.md)
- [SQLite and XCom](../guides/sqlite-and-xcom.md)
