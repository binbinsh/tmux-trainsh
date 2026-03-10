# 快速浏览

这一页给出一条最短且有用的 `trainsh` 上手路径。

## 1. 配置密钥

```bash
train secrets set VAST_API_KEY
train secrets set HF_TOKEN
```

## 2. 添加主机

可以使用本地、SSH、Colab 或 Vast 主机：

```bash
train host add
train host list
train host test <name>
```

## 3. 如需产物，再添加存储

```bash
train storage add
train storage list
train storage test <name>
```

## 4. 生成起始 recipe

```bash
train recipes new demo --template minimal
train recipes show demo
train help recipe
```

## 5. 运行 recipe

```bash
train run demo
train status
train logs
```

## 6. 中断后恢复

```bash
train resume demo
```

## 7. 继续阅读

- [编写第一个 recipe](tutorials/first-recipe.md)
- [运行远端 GPU 训练](tutorials/remote-gpu-training.md)
- [Package reference](package-reference/_index.md)
