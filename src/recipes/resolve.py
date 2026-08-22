"""Turning references into frozen macro snapshots.

Every failure here is named after the reference that caused it. That is the
whole point: the bug this port fixes reported an empty error list while
dropping two thirds of a recipe, because a lookup miss was a fulfilled
promise carrying no macros.
"""

from dataclasses import dataclass, replace
from pathlib import Path

from recipes import store
from recipes.models import NUTRIENT_KEYS, Ingredient, ProductLookup, Recipe


@dataclass(frozen=True)
class Resolved:
    """What one pass over a recipe's references produced.

    `resolved` and `changes` are deliberately separate: filling in an
    ingredient that had no macros is the normal course of authoring, while the
    database disagreeing with a frozen snapshot is news.

    `errors` refuses the recipe; `warnings` does not. The difference is
    whether there was a good snapshot to fall back on.
    """

    recipe: Recipe
    resolved: list[str]
    changes: list[dict]
    warnings: list[str]
    errors: list[str]


def _resolve_one(
    source: str, id: str, grams: float, lookup: ProductLookup
) -> tuple[Ingredient | None, str | None]:
    """Resolve one reference, reporting a miss instead of hiding it."""
    ref = f"{source}:{id}"
    # The lookup is injected code reading records this package does not own.
    # One unreadable record must name itself, not abort the whole command.
    try:
        product = lookup.lookup(source, id)
    except Exception as exc:  # noqa: BLE001
        return None, f"{ref}: {exc}"

    if product is None:
        return None, f"{ref}: product not found"

    resolved = Ingredient(
        source=source,
        id=id,
        grams=grams,
        name=product.name or ref,
        macros=product.macros(grams),
    )
    return resolved, None


def _changed_fields(before: Ingredient, after: Ingredient) -> dict[str, dict]:
    """Which stored fields the database now disagrees with.

    Only called for an ingredient that already carried a snapshot, so every
    field here is a disagreement rather than a first reading. An optional
    nutrient appearing or vanishing is one: it decides whether the recipe can
    be totalled for that nutrient at all, so it is reported with `None` on
    whichever side of the change lacked it.
    """
    fields: dict[str, dict] = {}
    if before.name != after.name:
        fields["name"] = {"before": before.name, "after": after.name}

    for key in NUTRIENT_KEYS:
        old, new = getattr(before.macros, key), getattr(after.macros, key)
        if old != new:
            fields[key] = {"before": old, "after": new}

    return fields


def resolve_recipe(
    recipe: Recipe, lookup: ProductLookup, *, force: bool = False
) -> Resolved:
    """Fill in every reference that has no macros yet, or all of them.

    An ingredient that already carries a snapshot is left untouched unless
    `force` asks for a re-read. That is what makes a second run a no-op, and
    what lets an already-resolved recipe be read with no product database at
    all.
    """
    ingredients: list[Ingredient] = []
    resolved: list[str] = []
    changes: list[dict] = []
    warnings: list[str] = []
    errors: list[str] = []

    for before in recipe.ingredients:
        if before.macros is not None and not force:
            ingredients.append(before)
            continue

        after, error = _resolve_one(
            before.source, before.id, before.grams, lookup
        )
        if after is None:
            ingredients.append(before)
            # A miss with a good snapshot behind it is stale, not wrong:
            # losing it to a briefly unavailable source would turn a complete
            # recipe into one that refuses to total. A miss with nothing
            # behind it is rule 12 and refuses the recipe.
            message = error or f"{before.ref}: unresolved"
            if before.macros is None:
                errors.append(message)
            else:
                warnings.append(message)
            continue

        if before.macros is None:
            resolved.append(f"{after.ref}: {after.name}")
        else:
            fields = _changed_fields(before, after)
            if fields:
                changes.append(
                    {"ref": after.ref, "name": after.name, "fields": fields}
                )

        ingredients.append(after)

    return Resolved(
        recipe=replace(recipe, ingredients=ingredients),
        resolved=resolved,
        changes=changes,
        warnings=warnings,
        errors=errors,
    )


def resolve_and_write(
    path: Path,
    recipe: Recipe,
    lookup: ProductLookup,
    *,
    force: bool = False,
) -> tuple[Resolved, bool]:
    """Resolve references and write the recipe if and only if it is complete.

    Rule 12: nothing is written for a recipe that still cannot be totalled.
    """
    if not recipe.ingredients:
        return (
            Resolved(
                recipe=recipe,
                resolved=[],
                changes=[],
                warnings=[],
                errors=[f"{recipe.name}: has no ingredients"],
            ),
            False,
        )

    outcome = resolve_recipe(recipe, lookup, force=force)
    if outcome.errors:
        return outcome, False

    written = store.write(path, outcome.recipe)
    return outcome, written
