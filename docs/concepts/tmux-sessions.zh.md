# tmux 会话

`trainsh` 把 tmux 作为长时间命令执行的持久化底座。

## 为什么 tmux 是核心

tmux 提供：

- 长生命周期的 shell 状态
- 可被轮询和等待的 pane 输出
- 终端断开后的重新连接能力
- 一个天然适合训练任务驻留的执行环境

## 面向 session 的 API

核心 API 是：

```python
main = session("main", on="gpu")
main(...)
main.bg(...)
main.idle(...)
main.wait(...)
main.close(...)
```

这套写法就是旧 session DSL 的 Python 替代方案。

## 相关页面

- [Session API](../package-reference/session-api.md)
- [编写第一个 recipe](../tutorials/first-recipe.md)
