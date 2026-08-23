# Recipes

Local YAML recipes with four operations: edit, view, resolve product
references through Pantry, and create a self-contained share link for Plate.

```console
recipes edit "Bean salad"
pantry --json lookup manual tofu | recipes edit "Bean salad" --input -
recipes show "Bean salad"
recipes resolve "Bean salad"
recipes share "Bean salad"
```

Recipes live in `~/.config/recipes` by default. Pass `--dir` to any command to
use another directory. Missing nutrient values are `null`; an explicit zero
remains zero. JSON food items are flat. Share links keep the
compressed `#r=` format understood by Plate; the payload uses the same fields.
Ingredient nutrients describe their `grams`, or 100 g when `grams` is absent;
because nutrition sources publish per 100 g, scale their figures to the portion
before appending one, and set `grams` for a source that omits it. `edit
--input` reports nutrients it can prove impossible under `warnings` without
refusing them. Recipe output describes one recipe serving and can be piped
directly to Nutrilog.
