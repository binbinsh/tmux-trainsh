# Storage Management System Design

> Status note: this is a legacy design document from an earlier UI/Rust architecture.
> The detailed original write-up is preserved in the Chinese translation of this page.
> Current CLI behavior and supported storage commands are documented in `README.md`, `docs/guides/hosts-and-storage.md`, and `docs/package-reference/storage.md`.

## Overview

This page summarizes an older storage-management design for `tmux-trainsh`.

That design assumed:

- a unified storage abstraction backed by `rclone`
- local, SSH, and cloud-backed storage endpoints
- a richer GUI/Tauri file browser and transfer queue
- sync rules and progress tracking at the UI layer

The current product path is CLI-first and Python-recipe-first. The surviving ideas are:

- named storage aliases
- storage inspection and test commands
- upload, download, copy, move, sync, and wait helpers
- object-store style metadata and existence checks

## Historical architecture

The original design split storage support into:

- a frontend storage page and file browser
- a Rust backend for CRUD, transfer orchestration, and rclone RPC
- embedded `librclone`
- backends such as local files, SSH/SFTP, and cloud object stores

## What still matters today

The important concepts that still map into the current system are:

- local versus remote versus object storage endpoints
- transfer orchestration as a first-class capability
- storage aliases as stable workflow inputs
- waiting on remote files or object keys as a workflow primitive

## Current references

For the actively supported implementation, use:

- [Hosts and storage](guides/hosts-and-storage.md)
- [Storage package reference](package-reference/storage.md)
- [Transfer package reference](package-reference/transfer.md)

If you need the full historical UI/Rust design details, open the Chinese translation of this page.
