"""The in-binary manual. An agent driving this CLI may have nothing else."""

GUIDE = """\
recipes -- a searchable store of your own recipes, with the arithmetic

WHAT THIS IS
  Primarily a data source: `search` answers "what can I cook under 400 kcal a
  serving with 30 g of protein" in the same candidate record eatout uses for
  restaurant meals, so an orchestrator merges the two. `resolve` freezes the
  macros of a recipe you wrote, and `fit` scales one proportionally.

  A product database (pantry) owns food identity and food records. This tool
  depends on it one way only, through a lookup it is given.

COMMANDS
  recipes search [--max-kcal N] [--min-protein N] [--limit N] [--dir D]
  recipes show <name> [--servings N] [--dir D]
  recipes resolve <name> [--force] [--dir D] [--products D]
  recipes fit <name> --max-kcal N --min-protein N [--dir D]
  recipes share <name> [--dir D]
  recipes skill install|uninstall|status
  recipes guide

  `resolve` is the only command that writes anything.

AUTHORING A RECIPE
  Write the YAML yourself; there is no `add` or `edit` flag set, because a text
  editor is better at editing than any flag set would be. Declare intent only
  -- a (source, id) reference and an amount -- and never transcribe a macro
  number by hand:

    name: Chicken Bowl
    servings: 2
    tags: [dinner]
    notes: |-
      Grill 6 min a side.
    ingredients:
      - source: coles
        id: '1047'
        grams: 200

  Then `recipes resolve "Chicken Bowl"` fills in each `name` and per-100g
  `macros` from the product database, lists what it filled in under
  `resolved`, and writes the file back. It is idempotent: an ingredient that
  already has macros is left alone, so a second run changes nothing and needs
  no product database at all.

  `--force` re-reads every reference instead. A database that disagrees with a
  frozen snapshot is news, reported under `changes` as
  {ref, name, fields: {kcal: {before, after}}}. An optional nutrient that has
  appeared or vanished is a change too, with null on the side that lacked it.

  A reference that cannot be resolved and has no snapshot to fall back on
  refuses the whole command and writes nothing (rule 12). Under --force, a
  reference that misses but already has a snapshot keeps it and is reported
  under `warnings`: stale is not the same as wrong.

  Sources are exactly: coles, woolworths, afcd, usda, manual. Anything else is
  refused when the file is read. IDs are source-native strings and may contain
  a colon.

WHERE RECIPES LIVE
  One YAML file per recipe in $XDG_CONFIG_HOME/recipes (or ~/.config/recipes),
  overridable with --dir. They are private user data and are never written
  into a checkout. Point --dir at a private git repo and git owns the history:
  two revisions of a recipe are two commits to one file. There is no revision
  log and no "newest wins" resolution.

  The `name:` field inside the file is the recipe's identity, matched trimmed
  and case-insensitively, so renaming a recipe in place is a supported edit.
  The filename is cosmetic: nothing is looked up by it, and `resolve` does not
  rename a file whose name has drifted. Two files claiming one name is refused,
  naming both paths -- picking one would answer with whichever the filesystem
  listed first. `search`, `show` and `resolve` all report the file's path.

NUTRIENTS
  Per 100 g, always, both in the product database and in the snapshot stored
  on each ingredient. Totals scale by grams / 100 at the last step.

  Each ingredient keeps BOTH the reference (source, id, grams) AND a frozen
  per-100g snapshot. The reference alone rots when a retailer renumbers its
  catalogue; the snapshot alone cannot be refreshed.

  A snapshot always carries kcal, protein, fat and carbs, and carries fiber
  and sugar when the product record states them. An optional nutrient the
  record did not state is absent, never 0 and never null.

  Totals are all-or-nothing per nutrient: total and per_serving report a
  nutrient only when every ingredient supplied it, and otherwise omit it and
  name the ingredients that lacked it under macros.missing, the same shape
  `unresolved` uses. A partial fibre total silently under-reports, which is
  worse than none. complete: true means the four required macros resolved and
  nothing more, so a question about fibre is answered by looking for fiber in
  the per-serving figures. show, resolve and fit publish those as
  macros.per_serving; a search record publishes them as detail.per_serving,
  because its top-level per_serving is the shared shape and always carries
  exactly the four macros.

INCOMPLETE RECIPES
  An ingredient with no macro snapshot is reported by name. No total, filter
  or fit is ever computed over a recipe that has one:

    resolve       fills it in, or refuses and writes nothing
    show          complete: false, macros: null, unresolved: [...]
    search        never a candidate; named under skipped_incomplete
    fit/share     refuse

  A missing value is never treated as zero. An inferred zero under-counts
  every total downstream and cannot be told from a real one.

SEARCH
  Emits the shared candidate record, ranked by protein per 100 kcal and then
  by name, so a merged list is ordered the same way whoever produced it:

    {"kind":"recipe","id":"chicken bowl","name":"Chicken Bowl",
     "per_serving":{"kcal":165,"protein":31,"fat":3.6,"carbs":0},
     "complete":true,"detail":{"servings":2,"ingredients":[...],"path":"..."}}

  `id` is the recipe's identity key, which show, resolve, fit and share all
  accept as a name. Everything recipe-specific is under `detail`, which
  nothing shared reads: detail.total and detail.per_serving carry every
  nutrient the recipe can report, and detail.missing names the ingredients
  behind any nutrient neither of them could. Matching nothing is exit 0 with
  an empty list. --limit 0 means no limit.

FIT
  One factor scales every amount. It never substitutes an ingredient or
  invents a meal, so fits: false is a genuine proportional conflict. It
  reports the shortfall as gap.protein_g and gap.kcal, and when the protein
  floor and the calorie ceiling cross, calorie_excess_at_min_protein says how
  far over the ceiling one serving would be at exactly the protein floor.
  Nothing is written: the scaled recipe is returned, not stored.

SHARE URLS
  recipes share prints <viewer>#r=<payload> and its character length, because
  a QR code is the real size constraint. The payload is
  base64url(raw_deflate(compact_json)) with padding stripped, in the fragment
  so it never reaches a server. It is self-contained -- resolved names and
  macros, not references -- so the page renders with no database and no
  network:

    {"v":1,"n":"Name","s":2,"t":"notes",
     "i":[["Ingredient",150,318,7.8,10.6,45]]}

  i entries are [name, grams, kcal, protein, fat, carbs], per 100 g like
  everything else. n and t are omitted when empty, s when it is 1. Optional
  nutrients are deliberately not carried: plate owns this format, the payload
  is bounded by QR capacity, and the viewer displays nothing but the four.

  The viewer address comes from $RECIPES_VIEWER_URL (or a .env file), and
  defaults to the deployed Plate page at
  https://mealtime-tools.github.io/plate/. Set it to point links at your own
  deployment. Reading a link back is the viewer's job; it offers
  "export YAML".

PRODUCT DATA
  Only resolve needs products. They are read from pantry-format JSONL in
  $XDG_CONFIG_HOME/pantry, or from --products DIR. Nothing here ever writes to
  that directory, and no credential of any kind is read. An already-resolved
  recipe needs no product data at all: its snapshots are what show, search,
  fit and share use.

OUTPUT
  --json emits exactly one JSON object on stdout, for failures too:

    {"ok":true,"data":{...}}
    {"ok":false,"error":{"message":"..."},"data":{"errors":["coles:404: ..."]}}

  Branch on `ok`. The `data` beside an error names the ingredients that caused
  it, so no message ever has to be parsed. Human output goes to stdout and
  never needs parsing.

EXIT CODES
  0  success
  1  usage error: bad flags, a refused resolve, an unconfigured viewer
  2  remote error (nothing here makes a network request today)
  3  a stated constraint did not hold: fit found no scaling factor
  4  unused: no command here escalates a warning
"""
