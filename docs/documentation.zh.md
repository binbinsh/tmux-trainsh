# 文档系统

`trainsh` 文档站由手写指南和自动生成的参考页面共同组成。

## 自动生成的部分

- `docs/cli-reference/*.md`：从真实 `train` 帮助输出生成
- `docs/package-reference/*.md`：从公开 `trainsh.pyrecipe` API 自动提取
- `docs/examples/*.md`：从内置示例 recipe 自动生成

生成或刷新这些页面：

```bash
python scripts/generate_docs.py
```

把完整 Hugo 文档树导出到另一个站点：

```bash
python scripts/generate_docs.py --output ~/Projects/Personal/trainsh-home/content/docs
```

## 手写页面

- `docs/_index.md`
- `docs/installation.md`
- `docs/quicktour.md`
- `docs/getting-started.md`
- `docs/tutorials/*`
- `docs/guides/*`
- `docs/concepts/*`
- `docs/python-recipes.md`
- `docs/recipe-design.md`
- `docs/storage-design.md`
- `docs/secrets.md`

这些页面用于解释工作流、心智模型、迁移建议和无法仅靠函数签名生成的架构信息。

## 集成目标

生成出来的树面向 Hugo 站点。当前主要消费方是 `trainsh-home`，这些页面会挂在 `/docs/` 下。
