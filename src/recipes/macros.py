"""Recipe arithmetic. The only place a macro total is ever computed.

A total exists only for a recipe whose every ingredient carries a snapshot.
There is deliberately no second, laxer path: the bug this port fixes was a
second implementation that treated a missing snapshot as zero.
"""

import math
from dataclasses import dataclass, field, replace

from recipes.models import (
    NUTRIENT_KEYS,
    OPTIONAL_NUTRIENT_KEYS,
    Ingredient,
    Recipe,
)

# A recipe is always at least one serving, so a label never divides by zero.
MIN_SERVINGS = 1


class IncompleteRecipe(Exception):
    """Raised instead of returning a number that would be understated."""

    def __init__(self, recipe: Recipe, errors: list[str]) -> None:
        joined = "; ".join(errors)
        super().__init__(
            f"{recipe.name}: cannot total an incomplete recipe: {joined}"
        )
        self.errors = errors


def round_js(value: float, places: int = 2) -> float:
    """Round half away from zero, matching the reference's `Math.round`.

    Python's built-in `round` is banker's rounding, which would disagree with
    every figure the TypeScript version ever printed.
    """
    power = 10**places
    scaled = value * power
    rounded = (
        math.floor(scaled + 0.5) if value >= 0 else math.ceil(scaled - 0.5)
    )
    return rounded / power


def compact_number(value: float) -> float | int:
    """Render a whole amount without a trailing `.0`.

    Shared by the YAML store and the share payload: `475` is what a human
    diffs and what the golden vectors pin, and `475.0` is neither.
    """
    return int(value) if float(value).is_integer() else float(value)


def parse_servings(value: object) -> int:
    """Coerce anything a file or a flag can hold into a serving count."""
    try:
        parsed = int(float(str(value)))
    except (TypeError, ValueError):
        return MIN_SERVINGS

    return max(MIN_SERVINGS, parsed)


def unresolved(recipe: Recipe) -> list[str]:
    """Name every ingredient that cannot contribute to a total."""
    return [
        f"{item.ref}: no macro snapshot"
        for item in recipe.ingredients
        if item.macros is None
    ]


def is_complete(recipe: Recipe) -> bool:
    """Whether every ingredient carries a usable per-100 g snapshot."""
    return bool(recipe.ingredients) and not unresolved(recipe)


def _missing_from(
    stated: list[tuple[str, dict[str, float]]],
) -> dict[str, list[str]]:
    """Name, per optional nutrient, every ingredient that does not state it.

    The same shape as `unresolved`, one level down: a nutrient only three of
    six ingredients state cannot be totalled, and the useful answer is which
    three, not a number that quietly under-reports the recipe.

    Takes the nutrients each ingredient states rather than the ingredients,
    so the caller can hand over the very dicts it is about to sum. Asking a
    snapshot's fields here instead would be a second rule that has to agree
    with `as_dict`, and the failure when they disagree is a `KeyError` from a
    total summing a key this said was there.
    """
    missing: dict[str, list[str]] = {}
    for key in OPTIONAL_NUTRIENT_KEYS:
        absent = [
            f"{ref}: no {key}" for ref, values in stated if key not in values
        ]
        if absent:
            missing[key] = absent

    return missing


def ingredient_macros(item: Ingredient) -> dict[str, float]:
    """Scale one frozen per-100 g snapshot by the amount used.

    Only the nutrients that snapshot carries: an absent one is not a zero.
    """
    if item.macros is None:
        raise ValueError(f"{item.ref}: no macro snapshot")

    factor = item.grams / 100
    return {
        key: value * factor for key, value in item.macros.as_dict().items()
    }


@dataclass(frozen=True)
class RecipeMacros:
    total: dict[str, float]
    per_serving: dict[str, float]
    # Why a nutrient is absent from both totals, keyed by nutrient. Empty for
    # a recipe every ingredient of which carried every nutrient.
    missing: dict[str, list[str]] = field(default_factory=dict)


def recipe_macros(recipe: Recipe) -> RecipeMacros:
    """Total a recipe, or refuse. Never a partial sum presented as a total."""
    errors = unresolved(recipe)
    if errors or not recipe.ingredients:
        raise IncompleteRecipe(recipe, errors or ["recipe has no ingredients"])

    servings = parse_servings(recipe.servings)

    # All or nothing per nutrient: one ingredient that never stated its fibre
    # makes a fibre total an under-report, which is worse than no total.
    # Scaled once, then both decided and summed from the same dicts, so what
    # counts as stated and what gets added up cannot come apart.
    scaled = [
        (item.ref, ingredient_macros(item)) for item in recipe.ingredients
    ]
    missing = _missing_from(scaled)
    totals = {key: 0.0 for key in NUTRIENT_KEYS if key not in missing}
    for _, values in scaled:
        for key in totals:
            totals[key] += values[key]

    return RecipeMacros(
        total={key: round_js(value) for key, value in totals.items()},
        per_serving={
            key: round_js(value / servings) for key, value in totals.items()
        },
        missing=missing,
    )


@dataclass(frozen=True)
class FitOutcome:
    fits: bool
    scale: float | None = None
    recipe: Recipe | None = None
    gap: dict[str, float] | None = None
    message: str = ""
    calorie_excess_at_min_protein: float | None = None


def _gap(
    current: dict[str, float], max_kcal: float, min_protein: float
) -> dict[str, float]:
    return {
        "protein_g": round_js(max(0.0, min_protein - current["protein"])),
        "kcal": round_js(max(0.0, current["kcal"] - max_kcal)),
    }


def _gap_message(gap: dict[str, float]) -> str:
    # `:g` so a whole number reads as "15g" and not "15.0g".
    parts = [
        f"need +{gap['protein_g']:g}g protein" if gap["protein_g"] else "",
        f"-{gap['kcal']:g} kcal" if gap["kcal"] else "",
    ]
    return (
        ", ".join(part for part in parts if part)
        or "constraints cannot be met by proportional scaling"
    )


def fit_recipe(
    recipe: Recipe, *, max_kcal: float, min_protein: float
) -> FitOutcome:
    """Scale every amount by the single proportional solution, or explain.

    One factor for the whole recipe: it never substitutes an ingredient or
    invents a meal, so `fits: false` is a real constraint conflict and not a
    failure to search hard enough.
    """
    current = recipe_macros(recipe).per_serving

    # No protein means no factor can ever reach the floor.
    if current["protein"] <= 0:
        gap = _gap(current, max_kcal, min_protein)
        return FitOutcome(fits=False, gap=gap, message=_gap_message(gap))

    protein_scale = min_protein / current["protein"]
    calorie_scale = (
        max_kcal / current["kcal"] if current["kcal"] > 0 else math.inf
    )

    # The protein floor and the calorie ceiling cross: report by how much.
    if protein_scale > calorie_scale:
        gap = _gap(current, max_kcal, min_protein)
        excess = round_js(max(0.0, current["kcal"] * protein_scale - max_kcal))
        return FitOutcome(
            fits=False,
            gap=gap,
            message=_gap_message(gap),
            calorie_excess_at_min_protein=excess,
        )

    # Scale up to the floor, down to the ceiling, or leave a fitting recipe be.
    if current["protein"] < min_protein:
        scale = protein_scale
    elif current["kcal"] > max_kcal:
        scale = calorie_scale
    else:
        scale = 1.0

    scaled = replace(
        recipe,
        ingredients=[
            replace(item, grams=round_js(item.grams * scale))
            for item in recipe.ingredients
        ],
    )
    return FitOutcome(fits=True, scale=round_js(scale, 4), recipe=scaled)
