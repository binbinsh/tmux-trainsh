# CLI reference

The CLI is organized around two ideas:

- top-level workflow commands for running, resuming, inspecting, and scheduling jobs
- resource management commands for hosts, storage, secrets, and cloud providers

Start with [Quicktour](../quicktour.md) if you want a task-oriented path through the product. Use this section when you need exact command syntax.

## Command index

| Command | Purpose | Page |
| --- | --- | --- |
| `train help` | Centralized help topics and entry points. | [Open](help.md) |
| `train run` | Run one recipe immediately. | [Open](run.md) |
| `train resume` | Resume the latest interrupted or failed run for one recipe. | [Open](resume.md) |
| `train status` | Inspect active and recent sessions. | [Open](status.md) |
| `train logs` | Inspect execution logs for the current or a specific job. | [Open](logs.md) |
| `train jobs` | Inspect recent job state history. | [Open](jobs.md) |
| `train schedule` | Run and inspect timed recipes. | [Open](schedule.md) |
| `train recipes` | Manage Python recipe files and starter templates. | [Open](recipes.md) |
| `train transfer` | Copy data between hosts and storage backends. | [Open](transfer.md) |
| `train host` | Manage SSH, local, Colab, and Vast-backed hosts. | [Open](host.md) |
| `train storage` | Manage storage backends such as local paths, R2, B2, and S3. | [Open](storage.md) |
| `train secrets` | Store and inspect API keys and credentials. | [Open](secrets.md) |
| `train config` | Inspect and update runtime and tmux configuration. | [Open](config.md) |
| `train vast` | Manage Vast.ai instances. | [Open](vast.md) |
| `train colab` | Manage Google Colab hosts. | [Open](colab.md) |
| `train pricing` | Inspect exchange rates and estimate costs. | [Open](pricing.md) |
| `train update` | Check for new trainsh releases. | [Open](update.md) |
