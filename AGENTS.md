# Instructions for trainsh Doppio

## General Instructions
- Always query context7 for the most recent docs and best practices.
- All comments, logs and documentations in English.
- Include only brief end-user instructions in the root README.md file.
- Place detailed development documentation in docs/*.md (use lowercase filenames).
- Always prioritize ast-grep (cmd: `sg`) over regex/string-replace for code manipulation, using AST patterns to ensure structural accuracy and avoid syntax errors. Examples:
    1. Swap Args: `sg run -p 'fn($A, $B)' -r 'fn($B, $A)'`
    2. Wrap Error: `sg run -p 'return $E' -r 'return wrap($E)'`
    3. API Update: `sg run -p 'user.id' -r 'user.get_id()'`
- No legacy code, no backward compatibility.

## Tauri App Instructions

### Tech Stack
- **Platform**: Tauri v2 + Rust (Tokio async runtime)
- **Frontend**: React 19 + Vite + TanStack (Router, Query, Form)
- **Styling**: Tailwind CSS v4 + NextUI
- **Remote**: gRPC (tonic + protobuf-ts)
- **Animations**: Motion (framer-motion)

### Rust Rules
- All `#[tauri::command]` must be async
- Use `thiserror` for errors, return `Result<T, CustomError>`
- gRPC client lives in Rust, frontend never connects directly

### Frontend Rules
- Wrap all Tauri commands in `src/lib/tauri-api.ts`
- Use TanStack Query for caching and state management
- Generate types from `.proto` files, keep types in sync

### UI Rules
- Use NextUI components first
- Root layout: `select-none cursor-default h-screen overflow-hidden`
- NextUI components + Motion for micro-interactions
- Add page transitions, hover effects, skeleton loading
- Use NextUI theming for consistent design

### Security Rules
- Minimize Tauri capabilities exposure
- Validate all inputs in Rust layer