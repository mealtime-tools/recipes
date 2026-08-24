"""The one description of a recipe every command emits.

Written once so the JSON keys, the completeness flag and the macro totals
cannot drift between `show`, `resolve`, `fit` and `search`.
"""

from collections.abc import Iterable

from recipes.macros import is_complete, recipe_macros, round_js, unresolved
from recipes.models import NUTRIENT_KEYS, Recipe


def ingredient_rows(recipe: Recipe) -> list[dict]:
    """Every ingredient as flat JSON."""
    return [
        {
            "source": item.source,
            "id": item.id,
            "grams": item.grams,
            "name": item.name,
            **(
                item.macros.as_dict()
                if item.macros
                else {key: None for key in NUTRIENT_KEYS}
            ),
        }
        for item in recipe.ingredients
    ]


def describe(recipe: Recipe) -> dict:
    """A recipe as JSON: its fields, its state, and totals only if entitled.

    `nutrients` is null exactly when `complete` is false. An agent cannot
    mistake a partial sum for a total. No share
    URL: building one needs a configured viewer, which only `share` has.
    """
    complete = is_complete(recipe)
    macros = recipe_macros(recipe) if complete else None
    grams = sum(item.grams for item in recipe.ingredients)

    return {
        "name": recipe.name,
        "servings": recipe.servings,
        "tags": list(recipe.tags),
        "notes": recipe.notes,
        "grams": (round_js(grams / recipe.servings) if grams else None),
        "ingredients": ingredient_rows(recipe),
        "complete": complete,
        "unresolved": unresolved(recipe),
        **{
            key: macros.per_serving.get(key) if macros else None
            for key in NUTRIENT_KEYS
        },
    }


def macro_summary(values: dict[str, float | None]) -> str:
    """Print the nutrients this recipe states, and zero only for zero.

    Unstated ones are left out rather than printed as a question mark: the
    vocabulary is 41 names wide and a typical recipe states four of them, so
    a fixed column list is a line of question marks. `--json` still answers
    which names were stated, because it carries every key.
    """
    return "  ".join(
        f"{key} {values[key]:g}"
        for key in NUTRIENT_KEYS
        if values.get(key) is not None
    )


def recipe_lines(item: dict) -> Iterable[str]:
    """Human output for one described recipe."""
    plural = "" if item["servings"] == 1 else "s"
    yield f"{item['name']}  ({item['servings']} serving{plural})"

    for ingredient in item["ingredients"]:
        name = (
            ingredient["name"] or f"{ingredient['source']}:{ingredient['id']}"
        )
        yield f"  {ingredient['grams']:g} g  {name}"

    if item["complete"]:
        yield f"  per serving  {macro_summary(item)}"

    # Named, so the next command can be about the missing ingredient rather
    # than about the recipe being mysteriously unusable.
    for error in item["unresolved"]:
        yield f"  unresolved: {error}"

    if item["notes"]:
        yield "  notes:"
        for line in item["notes"].splitlines():
            yield f"    {line}"
