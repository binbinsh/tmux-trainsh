# Package reference

This section is the technical reference for the Python authoring API exposed by:

```python
from trainsh.pyrecipe import *
```

Use it when you already understand the product shape and need exact top-level helper names, parameter names, or return types.

## Reference map

| Page | Focus | Link |
| --- | --- | --- |
| Recipe Authoring | The top-level authoring surface is where recipes start. Use these helpers to declare recipe metadata, variables, host aliases, storage aliases, executor settings, and shared defaults. | [Open](recipe-builder.md) |
| Basic Providers | These helpers cover shell commands, Python snippets, notifications, and a few direct task primitives. | [Open](basic-providers.md) |
| Workflow Helpers | Workflow helpers cover Git actions, host probes, SSH commands, value capture, and lightweight HTTP or file waits. | [Open](workflow-helpers.md) |
| Control Flow | Control-flow helpers implement latest-only behavior, branching, short-circuit checks, and condition waits. | [Open](control-flow.md) |
| Session API | A bound session object keeps follow-up steps attached to one tmux session. This is the main API for long-running remote work. | [Open](session-api.md) |
| HTTP and Network | HTTP helpers cover direct request aliases, JSON helpers, and polling-style sensors for service health checks. | [Open](network.md) |
| SQLite and XCom | SQLite helpers run local database queries, while XCom-style helpers persist and retrieve small runtime values through sqlite metadata. | [Open](sqlite-and-xcom.md) |
| Notifications and Misc | Misc helpers cover explicit failure steps, webhook-style notifications, and XCom push/pull operations. | [Open](notifications-and-misc.md) |
| Storage | Storage helpers upload, download, copy, move, sync, inspect, and wait on storage-backed paths. | [Open](storage.md) |
| Transfer | Transfer helpers move files or directories between local paths, remote hosts, and storage endpoints. | [Open](transfer.md) |
| Control Helpers | Control helpers manage tmux sessions directly, add sleeps, and define explicit trigger-rule join points. | [Open](control-helpers.md) |
| Public models | Factory functions and exported model objects. | [Open](public-models.md) |
