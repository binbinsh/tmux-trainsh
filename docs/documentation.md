# Documentation System

The `trainsh` documentation site combines hand-written guides with generated reference material.

## Generated sections

- `docs/cli-reference/*.md`: generated from the real `train` help output
- `docs/package-reference/*.md`: generated from the public `trainsh.pyrecipe` API surface
- `docs/examples/*.md`: generated from bundled example recipes

Generate or refresh those pages with:

```bash
python scripts/generate_docs.py
```

To export the full Hugo docs tree into another site:

```bash
python scripts/generate_docs.py --output ~/Projects/Personal/trainsh-home/content/docs
```

## Hand-written sections

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

These pages explain workflows, mental models, migration guidance, and architecture that cannot be generated from signatures alone.

## Integration target

The generated tree is intended for a Hugo site. The primary consumer is `trainsh-home`, where these pages live under `/docs/`.
