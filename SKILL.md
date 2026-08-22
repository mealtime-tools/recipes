---
name: recipes
description: Edit, view, resolve, and share the user's local recipes.
---

# Recipes

Use the CLI with `--json` when consuming output.

```console
recipes edit NAME --json
recipes edit NAME --input FILE|- --json
recipes show NAME --json
recipes resolve NAME --json
recipes share NAME --json
```

Use `--dir PATH` only when the user supplied a different recipe directory.
`resolve` refreshes product snapshots from Pantry. `share` returns a
self-contained Plate URL. Missing nutrient values are JSON `null`, not zero.
`edit --input` appends one Pantry, Eatout, Recipes, or Nutrilog item as an
ingredient. The item must have all four core nutrients. The flat item may carry
optional `grams`; without it, the values describe 100 g.
