# Quicktour

This page shows the shortest useful path through `trainsh`.

## 1. Configure secrets

```bash
train secrets set VAST_API_KEY
train secrets set HF_TOKEN
```

## 2. Add a host

Use a local, SSH, Colab, or Vast-backed host:

```bash
train host add
train host list
train host test <name>
```

## 3. Add storage if you need artifacts

```bash
train storage add
train storage list
train storage test <name>
```

## 4. Generate a starter recipe

```bash
train recipes new demo --template minimal
train recipes show demo
train help recipe
```

## 5. Run the recipe

```bash
train run demo
train status
train logs
```

## 6. Resume after interruption

```bash
train resume demo
```

## 7. Move into deeper docs

- [Write your first recipe](tutorials/first-recipe.md)
- [Run remote GPU training](tutorials/remote-gpu-training.md)
- [Package reference](package-reference/_index.md)
