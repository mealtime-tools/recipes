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
item with all four core nutrients. Missing nutrients remain `null`.

Nutrients describe the stated `grams`, or 100 g when `grams` is absent. USDA,
AFCD, Open Food Facts and Pantry all publish per 100 g, so passing those
figures beside a real portion weight silently multiplies the ingredient. Scale
them to the portion, or omit `grams` and let 100 g stand. One flour, first as a
42 g portion and then as the per-100 g source it was scaled from:

```json
{"name":"Buckwheat flour","grams":42,"kcal":153,"protein":5.5,"fat":1.4,"carbs":29.0}
{"name":"Buckwheat flour","kcal":364,"protein":13.2,"fat":3.4,"carbs":69.0}
```
