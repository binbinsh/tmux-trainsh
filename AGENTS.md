# Instructions for kitten-trainsh

kitten-trainsh is a plugin suite for training large language models using various cloud services and internet-based resources.

## General Instructions
- Always query context7 for the most recent docs and best practices.
- Always use `uv` (not pip or conda) for Python. Keep `.venv` in the project root.
- Prefer ast-grep (cmd: `sg`) over regex/string-replace for code manipulation.
- Prefer ripgrep (cmd: `rg`) over grep or find for file searching.
- Always fix issues at the root cause. Do not use workarounds, monkey patches, or dirty hacks.
- No backward compatibility; remove deprecated code paths immediately.
- After changes, clean up dead code, unused imports, and obsolete comments.
- All comments, logs and documentations in English.
- Include all possible end-user commands in the root README.md file, categorize them by frequences.
- Place detailed development documentation in docs/*.md (use lowercase filenames)

## Reference
- https://sw.kovidgoyal.net/kitty/kittens/developing-builtin-kittens/
- https://sw.kovidgoyal.net/kitty/kittens/custom/

