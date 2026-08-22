# recipes

A searchable store of your own recipes, plus the arithmetic, as a CLI for
agents and people.

```sh
# Recipes are authored by editing YAML. Declare intent, resolve the numbers.
cat > ~/.config/recipes/bowl.yaml <<'YAML'
name: Chicken Bowl
servings: 2
ingredients:
  - source: coles
    id: '1047'
    grams: 200
YAML

uv run recipes resolve "Chicken Bowl"
uv run recipes search --max-kcal 900 --min-protein 40
uv run recipes fit "Chicken Bowl" --max-kcal 900 --min-protein 50
uv run recipes share "Chicken Bowl"
```

`recipes guide` is the full manual and needs no network. `SKILL.md` is the
agent-facing contract, installable with `recipes skill install`.

## Design

`search` is the main entry point, and it emits the same candidate record
`eatout` does for restaurant meals, ranked the same way, so an orchestrator
can merge both streams and answer "what could I eat" from either. That shared
record lives in `agentcli`; nothing in it is recipe-specific.

Editing is the caller's job, not a flag set. An agent with a text editor is
better at restructuring a recipe than any `add`/`remove-ingredient` surface,
so the file declares intent — a `(source, id)` reference and an amount — and
`resolve` derives every macro number from the product database and freezes it.
That is the one thing a caller must never do by hand, and `resolve` is the one
command that writes.

Recipes are **private user data**: one YAML file each, in
`$XDG_CONFIG_HOME/recipes` or a `--dir` of your choosing, never in a
repository. Point `--dir` at a private git repo and git owns the history —
there is no revision log in the tool, because two revisions of a recipe are
two commits to one file. The `name:` field inside a file is its identity, so
lookups scan and match on it and renaming a recipe in place is safe; the
filename is cosmetic.

Every ingredient stores a product reference *and* a frozen per-100 g macro
snapshot, so a recipe survives a retailer renumbering its catalogue and totals
without a network. The snapshot keeps whatever the record stated: `kcal`,
`protein`, `fat` and `carbs` always, plus `fiber` and `sugar` when the product
database has them. `resolve --force` re-reads the references and reports what
changed, a nutrient appearing or vanishing included.

A share URL is **self-contained**: the payload carries resolved names and the
four required macros in the fragment, so the page renders with no database, no
network and no server ever seeing it. The viewer address defaults to the
deployed Plate page, `https://mealtime-tools.github.io/plate/`; set
`$RECIPES_VIEWER_URL` to point links at your own deployment instead. Reading a
link back is the viewer's job, so there is no `import`. Plate owns
the canonical [share wire format](https://github.com/owahltinez/plate#share-url-wire-format);
Recipes only produces it. Optional nutrients stay out of it: the payload is
bounded by QR capacity, every per-ingredient field is paid for once per
ingredient, and the viewer displays nothing but the four.

An ingredient that cannot be resolved is **named and refused**, never totalled
as if it were zero. That bug — a confident total that silently omitted 300 g of
a 450 g recipe — is why this port exists.

## Product data

Products come from a lookup this package is *given*, never from a database it
owns. The CLI reads pantry-format JSONL from `$XDG_CONFIG_HOME/pantry` or
`--products DIR`; `src/recipes/products.py` is the single seam onto Pantry.

## YAML store contract

Recipes are authored by editing YAML directly. The caller writes intent:
`name`, servings, notes, tags, and ingredient `(source, id, grams)`. `resolve`
derives names and frozen per-100 g macros, validates them, and writes back. It
is idempotent; `--force` refreshes existing snapshots and reports changes.
There are no add/edit/remove verbs and no other command writes.

Frozen macros keep recipes useful offline and after retailer-id churn. The
`name:` inside the YAML file is authoritative; filenames are cosmetic slugs,
so lookup scans files and refuses two documents claiming the same name.
Recipes live only under XDG config or `--dir`, never in this repository.

An ingredient with an unresolved, missing, stringified, or non-numeric macro
is an error and the recipe refuses to total. Missing is not zero. Totals scale
per-100 g values by `grams / 100`, and displayed rounding is half away from
zero to match JavaScript rather than Python's banker rounding.

The four macros are required of every snapshot. `fiber` and `sugar` are
written only when the product record stated them, and are absent — never
`0`, never `null` — when it did not: a record that never stated its fibre is
not one stating zero. Totals are **all-or-nothing per nutrient**. `total` and
`per_serving` report a nutrient only when every ingredient supplied it, and
otherwise omit it and name the ingredients that lacked it under
`macros.missing`, the way an unresolvable ingredient is named under
`unresolved`. A partial fibre total silently under-reports, which is worse
than no total at all. `complete` still means the four required macros
resolved and says nothing about the rest, so a caller filtering on fibre
reads the keys of `per_serving` rather than `complete`.

## Development

```sh
uv run pytest -q
uvx ruff check src tests --line-length 79
```

`tests/codec_test.py` pins the share payload to repository-local
`codec-vectors.json`. Those are a
**decode-direction** golden: every `encoded` string must decode to its exact
`payload`. This encoder happens to reproduce the bytes too, which is asserted
here but is not a portable requirement — any valid raw-deflate stream is a
conformant encoding.

## Licence

MIT.
