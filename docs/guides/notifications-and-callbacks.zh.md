# 通知与回调

通知是普通的 recipe step。回调则是附着在 step 上、在成功或失败后触发的选项。

## 通知步骤

```python
notice("training finished")
slack("training finished", webhook="$SLACK_WEBHOOK")
email_send("training finished", title="Run complete")
```

## 回调

```python
defaults(
    on_success=["echo success {step_id}"],
    on_failure=["echo failure {step_id}"],
)
```

回调可以是命令风格字符串、provider 风格回调，或者在支持场景中的 Python callable。

## 失败处理

使用 `fail(...)` 明确声明一个终止失败点：

```python
fail("health check failed", after=health)
```

## 相关页面

- [Notifications and misc reference](../package-reference/notifications-and-misc.md)
- [Basic providers](../package-reference/basic-providers.md)
