"""The recipe record, and the narrow seam onto a product database.

Every ingredient carries both a reference `(source, id)` and a frozen
per-100 g macro snapshot. The reference alone rots when a retailer renumbers
its catalogue and is useless offline; the snapshot alone cannot be refreshed.
Keeping both is what lets a recipe outlive the database it came from.
"""

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

# `overlay` is storage, never a source; see SPEC.
PRODUCT_SOURCES = ("coles", "woolworths", "afcd", "usda", "manual")

# The four a snapshot must carry to be usable for arithmetic at all.
MACRO_KEYS = ("kcal", "protein", "fat", "carbs")

# Carried when the source record has them and absent when it does not, so a
# record that never stated its fibre cannot be read as one stating zero.
OPTIONAL_NUTRIENT_KEYS = ("fiber", "sugar")

# Every nutrient a snapshot may carry, in the order everything renders them.
NUTRIENT_KEYS = MACRO_KEYS + OPTIONAL_NUTRIENT_KEYS


@dataclass(frozen=True)
class Macros:
    """Per 100 g, always. Consumers scale by `grams / 100` at the last step."""

    kcal: float
    protein: float
    fat: float
    carbs: float
    fiber: float | None = None
    sugar: float | None = None

    def as_dict(self) -> dict[str, float]:
        """Only the nutrients this snapshot has. An absent one is no key.

        Omitted rather than written null: the YAML store and the JSON
        description both read this, and `fiber: null` in a file invites the
        next reader to treat it as a number.
        """
        values = {key: getattr(self, key) for key in MACRO_KEYS}
        for key in OPTIONAL_NUTRIENT_KEYS:
            if getattr(self, key) is not None:
                values[key] = getattr(self, key)

        return values


@dataclass(frozen=True)
class Product:
    """The part of a product database record a recipe needs.

    Deliberately not pantry's record type: recipes depends on a lookup, not on
    a database, and this keeps the dependency one directional and testable.
    """

    name: str
    kcal: float
    protein: float
    fat: float
    carbs: float
    fiber: float | None = None
    sugar: float | None = None
    source: str = ""
    id: str = ""
    brand: str = ""

    def macros(self) -> Macros:
        return Macros(**{key: getattr(self, key) for key in NUTRIENT_KEYS})

    def as_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "id": self.id,
            "name": self.name,
            "brand": self.brand,
            "macros": self.macros().as_dict(),
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
