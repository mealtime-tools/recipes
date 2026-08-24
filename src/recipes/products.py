"""Where a product reference is resolved. The one seam onto a database.

Recipes owns arithmetic and never owns products, so it depends on the
`ProductLookup` protocol rather than on any particular database. Tests inject
a fake; the CLI injects the reader below.

SEAM: when the Python `pantry` package lands, this is the only file that
changes. `resolve_lookup` returns its local product source instead of
`JsonlProducts`, and nothing else in this package needs to know.
"""

import json
import os
from math import isfinite
from pathlib import Path

import click
from mealtime_nutrients import CORE_NUTRIENTS, OPTIONAL_NUTRIENTS
from pantry import data as pantry_data
from pantry.store import Store

from recipes.models import Macros, Product, ProductLookup


class ProductError(Exception):
    """A record was found but cannot be used for arithmetic."""


def products_dir(env: dict[str, str] | None = None) -> Path:
    """Pantry's user data directory. Nothing here ever writes to it."""
    environ = os.environ if env is None else env
    base = environ.get("XDG_CONFIG_HOME") or ""
    root = Path(base) if base else Path.home() / ".config"
    return root / "pantry"


def product_from_record(record: dict) -> Product:
    """Read one Pantry record with whole-item nutrients and optional weight.

    Energy is read from `kcal` and nowhere else. A record stating only `kj` is
    refused rather than converted: pantry converts at ingestion, `kj` is not a
    name in the shared vocabulary, and a second conversion here is a second
    place for the ratio to be wrong. A missing figure is refused rather than
    defaulted: an inferred zero under-counts every recipe using the product.
    """
    values: dict[str, float] = {}
    for field in CORE_NUTRIENTS:
        if record.get(field) is None:
            raise ProductError(f"record carries no {field}")
        values[field] = float(record[field])

    # Left unset when the record does not state it: pantry infers no zero.
    for field in OPTIONAL_NUTRIENTS:
        if record.get(field) is not None:
            values[field] = float(record[field])

    # `NaN` and `Infinity` are readable JSON and crash `round_js` later.
    for field, value in values.items():
        if not isfinite(value):
            raise ProductError(f"record has an unusable {field}: {value}")

    return Product(
        name=str(record.get("name") or ""),
        source=str(record.get("source") or ""),
        id=str(record.get("id") or ""),
        brand=str(record.get("brand") or ""),
        grams=(
            float(record["grams"]) if record.get("grams") is not None else None
        ),
        nutrients=Macros(**values),
    )


class PantryProducts:
    """Pantry's owned shards and user overlay behind ProductLookup."""

    def __init__(self, store: Store) -> None:
        self.store = store

    def lookup(self, source: str, id: str) -> Product | None:
        record = self.store.find(source, id)
        return product_from_record(record) if record is not None else None


class JsonlProducts:
    """Products read from pantry-format JSONL files, loaded on first use.

    A shard omits `source` because its filename supplies it; a combined asset
    carries it explicitly. Both forms are accepted.
    """

    def __init__(self, paths: list[Path]) -> None:
        self.paths = paths
        self._index: dict[tuple[str, str], Product] | None = None

    def _load(self) -> None:
        index: dict[tuple[str, str], Product] = {}
        for path in self.paths:
            for number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), start=1
            ):
                if not line.strip():
                    continue

                try:
                    record = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ProductError(
                        f"{path.name}: line {number} is invalid JSON: {exc}"
                    ) from exc

                if not isinstance(record, dict):
                    raise ProductError(
                        f"{path.name}: line {number} must be a JSON object"
                    )

                source = str(record.get("source") or path.stem)
                record["source"] = source
                product = product_from_record(record)
                index[(source, str(record.get("id")))] = product

        self._index = index

    def lookup(self, source: str, id: str) -> Product | None:
        if self._index is None:
            self._load()
        assert self._index is not None
        return self._index.get((source, id))


def resolve_lookup(
    ctx: click.Context | None, directory: Path | None
) -> ProductLookup:
    """The injected lookup, an explicit export, or Pantry's local store."""
    if ctx is not None and ctx.obj is not None:
        return ctx.obj

    if directory is not None:
        return JsonlProducts(sorted(directory.glob("*.jsonl")))

    # Pantry's store is a directory of per-source shards.
    store = Store(
        lambda: pantry_data.read_shards(pantry_data.data_dir()),
        products_dir(),
    )
    return PantryProducts(store)
