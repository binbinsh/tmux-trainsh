# Notifications and callbacks

Notifications are normal recipe steps. Callbacks are step options that run after success or failure.

## Notification steps

```python
notice("training finished")
slack("training finished", webhook="$SLACK_WEBHOOK")
email_send("training finished", title="Run complete")
```

## Callbacks

```python
defaults(
    on_success=["echo success {step_id}"],
    on_failure=["echo failure {step_id}"],
)
```

Callbacks can be command-like strings, provider-style callbacks, or callables in supported contexts.

## Failure handling

Use `fail(...)` for an explicit terminal failure point:

```python
fail("health check failed", after=health)
```

## Related pages

- [Notifications and misc reference](../package-reference/notifications-and-misc.md)
- [Basic providers](../package-reference/basic-providers.md)
