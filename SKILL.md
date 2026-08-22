---
name: recipes
description: Search, total, scale and share the user's own recipes through the recipes CLI. Use when a user asks what they could cook under a calorie or protein constraint, asks about a saved recipe or its macros, wants a recipe scaled, wants a shareable link for one, or wants to add or edit a recipe.
---

# recipes

A searchable store of the user's own recipes, plus the arithmetic. `search` is
the main entry point: it answers "what can I cook under 400 kcal a serving
with 30 g of protein" in the same candidate record `eatout` emits for
restaurant meals, so results from both can be merged and compared directly.

A product database (pantry) owns food identity and food records; this tool
depends on it one way only, through an injected lookup.

Pass `--json` on every command: it emits exactly one object on stdout, and the
exit status is part of the contract.

```
{"ok": true,  "data": {...}}
{"ok": false, "error": {"message": "..."}, "data": {"errors": [...]}}
```

Branch on `ok`; the `data` beside an error names what caused it, so no message
has to be parsed. Exit codes: `0` success, `1` usage error or refused input,
`2` remote error, `3` a stated constraint did not hold (`fit` found no
factor). `4` is unused here.

## Commands

```sh
recipes search [--max-kcal N] [--min-protein N] [--limit N] [--dir D] --json
recipes show <name> [--servings N] [--dir D] --json
recipes resolve <name> [--force] [--dir D] [--products D] --json
recipes fit <name> --max-kcal N --min-protein N [--dir D] --json
recipes share <name> [--dir D] --json
recipes guide
recipes skill install|uninstall|status
```

`resolve` is the only command that writes anything. `recipes guide` prints the
full manual, offline and with no network.

## Authoring and editing: write the YAML, then resolve

There is no `add`, `edit` or `remove-ingredient` flag set. Edit the file
directly — you are a better text editor than any flag set. Write **intent
only**: a `(source, id)` reference and an amount. Never transcribe a macro
number by hand.

```yaml
name: Chicken Bowl
servings: 2
tags: [dinner]
notes: |-
  Grill 6 min a side.
ingredients:
  - source: coles
    id: '1047'
    grams: 200
```

Then `recipes resolve "Chicken Bowl" --json` fills in each `name` and
per-100 g `macros` from the product database and writes the file back. A
snapshot always carries `kcal`, `protein`, `fat` and `carbs`, and also
`fiber` and `sugar` when the record states them.

- Each ingredient it filled in is listed under `resolved`.
- **Idempotent.** An ingredient that already carries macros is left alone, so
  a second run reports `written: false`, `resolved: []`, `changes: []` and
  needs no product database at all.
- **`--force`** re-reads every reference. A database that disagrees with a
  frozen snapshot is news, reported under `changes` as
  `{ref, name, fields: {kcal: {before, after}}}`. An optional nutrient that
  has appeared or vanished is a change too, with `null` on the side that
  lacked it: it decides whether the recipe can be totalled for that nutrient.
- A reference that cannot be resolved and has no snapshot behind it refuses
  the command and writes nothing. Fix the reference, or use `source: manual`.
- Under `--force`, a reference that misses but already has a snapshot keeps it
  and is reported under `warnings`: stale is not the same as wrong.

Sources are exactly `coles`, `woolworths`, `afcd`, `usda`, `manual`; anything
else is refused when the file is read. IDs are source-native strings and may
contain a colon.

## search — the candidate record

```json
{"kind":"recipe","id":"chicken bowl","name":"Chicken Bowl",
 "per_serving":{"kcal":165.0,"protein":31.0,"fat":3.6,"carbs":0.0},
 "complete":true,"detail":{"servings":2,"tags":["dinner"],"notes":"...",
 "ingredients":[...],"total":{...},"per_serving":{...},"unresolved":[],
 "path":"/…/bowl.yaml"}}
```

Ranked by protein per 100 kcal, ties by name, so a list merged with eatout's
is ordered the same way whoever produced it. Everything recipe-specific is
under `detail`, which nothing shared reads — including `detail.per_serving`,
which carries every nutrient the recipe can report, where the top-level
`per_serving` is fixed at agentcli's four macros. `id` is the recipe's
identity key and is accepted as the `<name>` argument of `show`, `resolve`,
`fit` and `share`; `detail.path` is the file to edit.

Matching nothing is exit `0` with `candidates: []`. `--limit 0` means no
limit. Recipes whose macros cannot be totalled are never candidates and are
listed under `skipped_incomplete` as `{name, unresolved}` — "nothing matched"
and "two I could not check" are different answers.

## Incomplete recipes are refused, never estimated

An ingredient with no macro snapshot is reported by name, and no total, filter
or fit is computed over a recipe that has one:

| command | behaviour |
| --- | --- |
| `resolve` | fills it in, or refuses and writes nothing, listing the failures under `data.errors` |
| `show` | `complete: false`, `macros: null`, `unresolved: [...]` |
| `search` | never a candidate; named under `skipped_incomplete` |
| `fit`, `share` | refuse |

Treat `complete: false` as a hard stop for any macro decision. A missing value
is never treated as zero: an inferred zero under-counts every total
downstream and cannot be told from a real one.

## Totals are all-or-nothing per nutrient

`total` and `per_serving` report a nutrient only when **every** ingredient
supplied it. A nutrient one ingredient lacks is omitted from both, and its
absence from the keys is how you know:

```json
{"total":{"kcal":1517.0,"protein":66.6,"fat":30.2,"carbs":247.8,"fiber":10.8},
 "per_serving":{...}}
```

Sugar is absent above because at least one ingredient never stated it.

A partial fibre total silently under-reports, so there is no partial total.
`complete: true` means the four required macros resolved and nothing more, so
to decide whether a recipe can answer a question about fibre, look for `fiber`
in the per-serving figures — not `complete`.

Which figures depends on the command. `show`, `resolve` and `fit` return
`macros.total` and `macros.per_serving`, both of which carry every nutrient.
A `search` record's top-level `per_serving` is agentcli's shared shape and is
**always** exactly the four macros, so read `detail.per_serving` and
`detail.total` there instead. Never
divide a total by `servings` yourself; a per-serving figure is always
published.

## Where recipes live

One YAML file per recipe in `$XDG_CONFIG_HOME/recipes` (or
`~/.config/recipes`), overridable with `--dir`. They are private user data and
are never written into a checkout. Point `--dir` at a private git repo and git
owns the history: two revisions of a recipe are two commits to one file.

The `name:` field inside the file is the identity, matched trimmed and
case-insensitively, so renaming a recipe in place is a supported edit. The
filename is cosmetic — nothing is looked up by it, and `resolve` does not
rename a file whose name has drifted. Two files claiming one name is refused,
naming both paths.

Each ingredient carries BOTH the reference `(source, id, grams)` AND a frozen
per-100 g snapshot once resolved. The reference alone rots when a retailer
renumbers its catalogue and is useless offline; the snapshot alone cannot be
refreshed.

Nutrients are per 100 g everywhere, in the database and in the snapshot.
Totals scale by `grams / 100` at the last step. `fiber` and `sugar` are
written only when the source record stated them and are absent otherwise —
never `0` and never `null`, because a record that never stated its fibre is
not one stating zero.

## fit

One factor scales every amount, and nothing is written. It never substitutes
an ingredient or invents a meal, so `fits: false` is a genuine proportional
conflict, reported as `gap.protein_g` and `gap.kcal` per serving, plus
`calorie_excess_at_min_protein`: how far over the ceiling one serving would be
at exactly the protein floor.

## share

`recipes share` prints `<viewer>#r=<payload>` and its character length, because
a QR code is the real size constraint (an 11-ingredient recipe with a 3-line
note measures about 630 characters).

The viewer base URL comes from `$RECIPES_VIEWER_URL`, or a `.env` file, and
defaults to the deployed Plate page,
`https://mealtime-tools.github.io/plate/`. Set
the variable to point links at a different deployment.

The link is self-contained and carries resolved names and the four required
macros rather than references; optional nutrients are deliberately left out,
since the payload is bounded by QR capacity and the viewer displays nothing
else. Plate owns the canonical
[wire format](https://github.com/owahltinez/plate#share-url-wire-format) and
offers "export YAML". This CLI has no `import`.

## Product data

Only `resolve` needs products. It reads pantry-format JSONL from
`$XDG_CONFIG_HOME/pantry`, or from `--products DIR`. Nothing here ever writes
to that directory. No `USDA_API_KEY` or any other credential is read by this
tool.
