"""Recipe arithmetic. The only place a macro total is ever computed.

A total exists only for a recipe whose every ingredient carries a snapshot.
There is deliberately no second, laxer path: the bug this port fixes was a
second implementation that treated a missing snapshot as zero.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from mealtime_nutrients import NUTRIENTS, OPTIONAL_NUTRIENTS

from recipes.models import Ingredient, Recipe

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


def round_js(value: Decimal, places: int = 2) -> Decimal:
    """Round half away from zero, matching the reference's `Math.round`.

    Python's built-in `round` is banker's rounding, which would disagree with
    every figure the TypeScript version ever printed. `ROUND_HALF_UP` is the
    decimal spelling of the same rule for a non-negative figure, and every
    nutrient is one. It parts from `Math.round` only below zero, where
    JavaScript sends a tie towards `+Infinity`: `Math.round(-0.5)` is `-0`.
    """
    return value.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)


def figure_number(value: Decimal | None) -> int | float | None:
    """One figure as the plain number a YAML or JSON document can hold.

    Neither format has a decimal type, so a figure is written as the number
    that denotes it: an integer where the decimal has no fractional digits,
    and otherwise the double `float` gives -- which prints as the shortest
    text that reads back, and is the value every share link already carries.
    """
    if value is None:
        return None

    # A non-finite exponent is `'n'`, `'N'` or `'F'`, never a place count.
    exponent = value.as_tuple().exponent
    if not isinstance(exponent, int) or exponent < 0:
        return float(value)

    return int(value)


def figure_numbers(
    values: Mapping[str, Decimal | None],
) -> dict[str, int | float | None]:
    """`figure_number` over one nutrient mapping, order intact."""
    return {key: figure_number(value) for key, value in values.items()}


def compact_number(value: float) -> float | int:
    """Render a whole amount without a trailing `.0`.

    Shared by the YAML store and the share payload: `475` is what a human
    diffs and what the golden vectors pin, and `475.0` is neither. Weights,
    not figures: a weight is authored, so it never accumulates arithmetic.
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
    """Whether every ingredient carries a usable nutrient snapshot."""
    return bool(recipe.ingredients) and not unresolved(recipe)


def _absent_from(
    stated: list[tuple[str, dict[str, Decimal | None]]],
) -> set[str]:
    """Every optional nutrient at least one ingredient does not state.

    A nutrient only three of six ingredients state cannot be totalled: the
    sum would quietly under-report. Takes the nutrients each ingredient
    states rather than the ingredients, so the caller hands over the very
    dicts it is about to sum and what counts as stated cannot come apart
    from what gets added up.
    """
    return {
        key
        for key in OPTIONAL_NUTRIENTS
        for _, values in stated
        if values.get(key) is None
    }


def ingredient_macros(item: Ingredient) -> dict[str, Decimal | None]:
    """Return the nutrients stored for this ingredient."""
    if item.macros is None:
        raise ValueError(f"{item.ref}: no macro snapshot")

    return item.macros.as_dict()


@dataclass(frozen=True)
class RecipeMacros:
    total: dict[str, Decimal]
    per_serving: dict[str, Decimal]


def recipe_macros(recipe: Recipe) -> RecipeMacros:
    """Total a recipe, or refuse. Never a partial sum presented as a total."""
    errors = unresolved(recipe)
    if errors or not recipe.ingredients:
        raise IncompleteRecipe(recipe, errors or ["recipe has no ingredients"])

    servings = parse_servings(recipe.servings)

    # All or nothing per nutrient: one unstated reading voids that total.
    scaled = [
        (item.ref, ingredient_macros(item)) for item in recipe.ingredients
    ]
    absent = _absent_from(scaled)
    totals = {key: Decimal(0) for key in NUTRIENTS if key not in absent}
    for _, values in scaled:
        for key in totals:
            value = values[key]
            assert value is not None
            totals[key] += value

    divisor = Decimal(servings)
    return RecipeMacros(
        total={key: round_js(value) for key, value in totals.items()},
        per_serving={
            key: round_js(value / divisor) for key, value in totals.items()
        },
    )
