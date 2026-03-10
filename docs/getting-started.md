# Getting started

This page is the practical setup checklist. If you want a shorter walkthrough, start with [Quicktour](quicktour.md).

## Install and verify

Follow [Installation](installation.md), then verify:

```bash
train --help
train help recipe
tmux -V
```

## Configure secrets

Set the credentials your workflows need:

```bash
train secrets set VAST_API_KEY
train secrets set HF_TOKEN
train secrets set OPENAI_API_KEY
```

## Add compute

Add at least one host:

```bash
train host add
train host list
train host test <name>
```

## Add storage

If your workflows publish or pull artifacts:

```bash
train storage add
train storage list
train storage test <name>
```

## Create and inspect a recipe

```bash
train recipes new demo --template minimal
train recipes show demo
train help recipe
```

## Run, inspect, and resume

```bash
train run demo
train status
train logs
train jobs
train resume demo
```

## Add scheduling metadata

Put scheduler metadata at the top of a recipe file:

```python
# schedule: @every 15m
# owner: ml
# tags: nightly,train
```

Then inspect or run the scheduler:

```bash
train schedule list
train schedule run --once
train schedule run --forever
train schedule status
```

## Continue with task-oriented docs

- [Write your first recipe](tutorials/first-recipe.md)
- [Run remote GPU training](tutorials/remote-gpu-training.md)
- [Build reliable workflows](tutorials/reliable-workflows.md)
- [Schedule and resume runs](tutorials/scheduling-and-resume.md)
