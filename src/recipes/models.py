"""The recipe record, and the narrow seam onto a product database.

Every ingredient carries both a reference `(source, id)` and frozen nutrients
for its actual weight. The reference alone rots when a retailer renumbers
its catalogue and is useless offline; the snapshot alone cannot be refreshed.
Keeping both is what lets a recipe outlive the database it came from.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

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

# The four a snapshot must carry to be usable for arithmetic at all.
MACRO_KEYS = CORE_NUTRIENTS

# The three optional nutrients the wire format carried before it widened, in
# the order it carried them. Restated rather than derived because this is
# history, not vocabulary: with the four macros they are the first seven keys
# of every share link ever made, and the payload has no version field.
_LEGACY_KEYS = ("fiber", "sodium", "sugar")

# Carried when the source record has them and absent when it does not, so a
# record that never stated its fibre cannot be read as one stating zero. The
# rest of the shared vocabulary is appended rather than merged, so the legacy
# names keep both their order and their positions, and sorted, so that adding
# a name to the library cannot reshuffle the ones before it.
OPTIONAL_NUTRIENT_KEYS = _LEGACY_KEYS + tuple(
    sorted(set(NUTRIENTS) - set(MACRO_KEYS) - set(_LEGACY_KEYS))
)

# Every nutrient a snapshot may carry, in the order everything renders them.
NUTRIENT_KEYS = MACRO_KEYS + OPTIONAL_NUTRIENT_KEYS


def _nutrients(values: Mapping[str, float | None]) -> dict[str, float | None]:
    """One nutrient mapping in `NUTRIENT_KEYS` order, missing keys as null.

    Key order lives here alone. Every wire format renders these keys in this
    order, and the share payload carries no version field, so a reordering
    would silently break links that already exist.
    """
    unknown = sorted(set(values) - set(NUTRIENT_KEYS))
    if unknown:
        raise TypeError(f"unknown nutrients: {', '.join(unknown)}")

    # Omitting one of the four is a caller bug, not an absent reading.
    missing = [key for key in MACRO_KEYS if key not in values]
    if missing:
        raise TypeError(f"missing nutrients: {', '.join(missing)}")

    return {key: values.get(key) for key in NUTRIENT_KEYS}


@dataclass(frozen=True, init=False)
class Macros:
    """Nutrients for one whole product or ingredient.

    One mapping rather than a field per nutrient: adding a nutrient is then a
    change to `NUTRIENT_KEYS` and nothing else. Kept private and copied on
    read so a frozen snapshot cannot be edited through it.
    """

    _values: dict[str, float | None]

    def __init__(self, **values: float | None) -> None:
        object.__setattr__(self, "_values", _nutrients(values))

    def as_dict(self) -> dict[str, float | None]:
        """Every standard nutrient. Unknown values are null, never zero.

        Not a wire format: nothing emits this. It is for the two readers that
        compare or total across the whole vocabulary, `resolve._changed_fields`
        and `macros.recipe_macros`, where a null column is the answer rather
        than noise -- a nutrient appearing or vanishing on a refresh is news,
        and one ingredient's absent fibre voids the recipe's fibre total.
        """
        return dict(self._values)

    def stated(self) -> dict[str, float | None]:
        """Only the nutrients this snapshot carries, in the same order.

        What everything emits. An absent key and an explicit null both read
        back as unstated, so the null is bytes in every stored recipe, share
        link and JSON row that buy nothing. The four macros are always
        written, so a reader still gets the shape it requires.
        """
        return {
            key: value
            for key, value in self._values.items()
            if value is not None or key in MACRO_KEYS
        }

    def scaled(self, factor: float) -> "Macros":
        """The same nutrients for `factor` times the weight.

        A nutrient the source never stated stays unstated: scaling an absent
        reading into a zero would report it as sourced.
        """
        return Macros(
            **{
                key: None if value is None else value * factor
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
        basis = self.grams or 100.0
        return self.nutrients.scaled((grams or basis) / basis)

    def as_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "id": self.id,
            "name": self.name,
            "brand": self.brand,
            "grams": self.grams,
            **self.macros().as_dict(),
        }


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
