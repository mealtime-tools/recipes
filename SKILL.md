---
name: recipes
description: Edit, view, resolve, and share the user's local recipes.
---

# Recipes

Use the CLI with `--json` when consuming output.

```console
recipes edit NAME [--input FILE|-] --json
recipes show NAME --json
recipes resolve NAME --json
recipes share NAME --json
```

Use `--dir PATH` only when the user supplied a different recipe directory.
`resolve` refreshes Pantry product snapshots. `share` returns a self-contained
Plate URL. `edit --input` appends one flat Pantry, Eatout, Recipes, or Nutrilog
item with all four core nutrients. Nutrients describe the stated `grams`, or
100 g when `grams` is absent. Missing nutrients remain `null`.
