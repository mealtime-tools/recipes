"""The recipe record, and the narrow seam onto a product database.

Every ingredient carries both a reference `(source, id)` and frozen nutrients
for its actual weight. The reference alone rots when a retailer renumbers
its catalogue and is useless offline; the snapshot alone cannot be refreshed.
Keeping both is what lets a recipe outlive the database it came from.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Protocol, runtime_checkable

from mealtime_nutrients import CORE_NUTRIENTS, NUTRIENTS

# `overlay` is storage, never a source; see SPEC.
PRODUCT_SOURCES = (
    "coles",
    "woolworths",
    "afcd",
    "usda",
    "openfoodfacts",
    "manual",
)

# What a figure may arrive as. Pantry and every JSON source still send floats.
Figure = Decimal | float | int | str


def to_decimal(value: Figure) -> Decimal:
    """One figure as a decimal, whatever the source handed over.

    A float is read through the shortest text that denotes it, so a source
    that wrote `0.5` yields `Decimal("0.5")` and not the binary expansion
    `Decimal(0.5)` would give. Refuses like `float` did, as a `ValueError`,
    because every caller already maps that onto its own refusal.
    """
    if isinstance(value, Decimal):
        return value

    try:
        return Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError(f"not a number: {value!r}") from exc


def _nutrients(
    values: Mapping[str, Figure | None],
) -> dict[str, Decimal | None]:
    """One nutrient mapping in `NUTRIENTS` order, missing keys as null.

    The share payload carries no version field, so the library's order is the
    wire order and a reordering there breaks links that already exist.
    """
    unknown = sorted(set(values) - set(NUTRIENTS))
    if unknown:
        raise TypeError(f"unknown nutrients: {', '.join(unknown)}")

    # Omitting one of the four is a caller bug, not an absent reading.
    missing = [key for key in CORE_NUTRIENTS if key not in values]
    if missing:
        raise TypeError(f"missing nutrients: {', '.join(missing)}")

    # Coerced here, so no snapshot anywhere can hold a binary float.
    stated = {key: values.get(key) for key in NUTRIENTS}
    return {
        key: None if value is None else to_decimal(value)
        for key, value in stated.items()
    }


@dataclass(frozen=True, init=False)
class Macros:
    """Nutrients for one whole product or ingredient.

    One mapping rather than a field per nutrient: adding a nutrient is then a
    change to the shared vocabulary and nothing else. Kept private and copied
    on read so a frozen snapshot cannot be edited through it.
    """

    _values: dict[str, Decimal | None]

    def __init__(self, **values: Figure | None) -> None:
        object.__setattr__(self, "_values", _nutrients(values))

    def as_dict(self) -> dict[str, Decimal | None]:
        """Every standard nutrient. Unknown values are null, never zero.

        Not a wire format: nothing emits this. It is for the two readers that
        compare or total across the whole vocabulary, `resolve._changed_fields`
        and `macros.recipe_macros`, where a null column is the answer rather
        than noise -- a nutrient appearing or vanishing on a refresh is news,
        and one ingredient's absent fibre voids the recipe's fibre total.
        """
        return dict(self._values)

    def stated(self) -> dict[str, Decimal | None]:
        """Only the nutrients this snapshot carries, in the same order.

        What everything emits. An absent key and an explicit null both read
        back as unstated, so the null is bytes in every stored recipe, share
        link and JSON row that buy nothing. The four macros are always
        written, so a reader still gets the shape it requires.
        """
        return {
            key: value
            for key, value in self._values.items()
            if value is not None or key in CORE_NUTRIENTS
        }

    def scaled(self, factor: Figure) -> "Macros":
        """The same nutrients for `factor` times the weight.

        Decimal throughout: as binary floats `2.8 * (10 / 100)` is
        `0.27999999999999997`, and that noise was landing in stored recipes
        and in share links.

        A nutrient the source never stated stays unstated: scaling an absent
        reading into a zero would report it as sourced.
        """
        multiplier = to_decimal(factor)
        return Macros(
            **{
                key: None if value is None else value * multiplier
                for key, value in self._values.items()
            }
        )


@dataclass(frozen=True)
class Product:
    """The part of a product database record a recipe needs.

    Deliberately not pantry's record type: recipes depends on a lookup, not on
    a database, and this keeps the dependency one directional and testable.
    """

    name: str
    nutrients: Macros
    source: str = ""
    id: str = ""
    brand: str = ""
    grams: float | None = None

    def macros(self, grams: float | None = None) -> Macros:
        """Nutrients for `grams`, or the record's own figures unscaled."""
        # Pantry's format: a record with no weight states per-100 g figures.
        basis = to_decimal(self.grams or 100)
        return self.nutrients.scaled(to_decimal(grams or basis) / basis)


@runtime_checkable
class ProductLookup(Protocol):
    """Resolves an explicit `(source, id)` pair, or reports a miss as None.

    A miss must be visible to the caller. The bug this port fixes came from a
    lookup whose miss was indistinguishable from a resolved product.
    """

    def lookup(self, source: str, id: str) -> Product | None: ...


@dataclass
class Ingredient:
    """A reference, an amount, and what the reference resolved to once."""

    source: str
    id: str
    grams: float
    name: str | None = None
    macros: Macros | None = None

    @property
    def ref(self) -> str:
        """The label every per-ingredient error is keyed by."""
        return f"{self.source}:{self.id}"


@dataclass
class Recipe:
    """One recipe: one YAML file, with git owning its history."""

    name: str
    servings: int = 1
    ingredients: list[Ingredient] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    notes: str = ""
    source_url: str = ""
