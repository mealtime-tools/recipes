"""The one description of a recipe every command emits.

Written once so the JSON keys, the completeness flag and the macro totals
cannot drift between `show`, `resolve`, `fit` and `search`.
"""

from collections.abc import Iterable

from recipes.macros import is_complete, recipe_macros, unresolved
from recipes.models import MACRO_KEYS, Recipe


def ingredient_rows(recipe: Recipe) -> list[dict]:
    """Every ingredient as JSON. `macros` is null when it never resolved."""
    return [
        {
            "source": item.source,
            "id": item.id,
            "grams": item.grams,
            "name": item.name,
            "macros": item.macros.as_dict() if item.macros else None,
        }
        for item in recipe.ingredients
    ]


def describe(recipe: Recipe) -> dict:
    """A recipe as JSON: its fields, its state, and totals only if entitled.

    `macros` is null exactly when `complete` is false. An agent that reads
    only `macros` therefore cannot mistake a partial sum for a total. No share
    URL: building one needs a configured viewer, which only `share` has.
    """
    complete = is_complete(recipe)
    macros = recipe_macros(recipe) if complete else None

    return {
        "name": recipe.name,
        "servings": recipe.servings,
        "tags": list(recipe.tags),
        "notes": recipe.notes,
        "ingredients": ingredient_rows(recipe),
        "complete": complete,
        "unresolved": unresolved(recipe),
        "macros": (
            {"total": macros.total, "per_serving": macros.per_serving}
            if macros
            else None
        ),
    }


def macro_summary(values: dict[str, float]) -> str:
    """Only the macros there are: a missing one is absent, never printed 0."""
    return "  ".join(
        f"{key} {values[key]:g}" for key in MACRO_KEYS if key in values
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

    if item["macros"]:
        yield f"  total        {macro_summary(item['macros']['total'])}"
        yield f"  per serving  {macro_summary(item['macros']['per_serving'])}"

    # Named, so the next command can be about the missing ingredient rather
    # than about the recipe being mysteriously unusable.
    for error in item["unresolved"]:
        yield f"  unresolved: {error}"

    if item["notes"]:
        yield "  notes:"
        for line in item["notes"].splitlines():
            yield f"    {line}"
