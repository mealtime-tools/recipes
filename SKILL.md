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
AFCD, Open Food Facts and Pantry all publish per 100 g, so scale their figures
to the portion before appending. Getting this wrong is silent and cuts both
ways: per-100 g figures beside a smaller `grams` overstate the ingredient, and
figures already scaled to a portion with `grams` omitted understate it, because
they are then read as describing 100 g. Omit `grams` only when the portion
really is 100 g. Pantry's AFCD records carry no `grams` at all, so set it
yourself rather than letting the item land as 100 g.

A 42 g portion of flour:

```json
{"name":"Buckwheat flour","grams":42,"kcal":153,"protein":5.5,"fat":1.4,"carbs":29.0}
```

The per-100 g source it was scaled from, which is a different ingredient:

```json
{"name":"Buckwheat flour","grams":100,"kcal":364,"protein":13.2,"fat":3.4,"carbs":69.0}
```

`edit --input` lists impossible nutrients under `warnings` and still appends
the item. An empty list is not a guarantee: a plausible number can be wrong,
and no check catches an understatement.
