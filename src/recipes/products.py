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
from typing import Any

import click
from pantry import data as pantry_data
from pantry.local import Local
from pantry.store import Store

from recipes.models import (
    MACRO_KEYS,
    OPTIONAL_NUTRIENT_KEYS,
    Product,
    ProductLookup,
)

# kJ per kcal, for records that carry only the SI figure.
KJ_PER_KCAL = 4.184


class ProductError(Exception):
    """A record was found but cannot be used for arithmetic."""


def products_dir(env: dict[str, str] | None = None) -> Path:
    """Pantry's user data directory. Nothing here ever writes to it."""
    environ = os.environ if env is None else env
    base = environ.get("XDG_CONFIG_HOME") or ""
    root = Path(base) if base else Path.home() / ".config"
    return root / "pantry"


def _kcal(record: dict) -> float:
    """Energy in kcal, converted from kJ only when kcal is absent.

    A missing figure is refused rather than defaulted: an inferred zero
    silently under-counts every recipe that uses the product.
    """
    if record.get("kcal") is not None:
        return float(record["kcal"])

    if record.get("kj") is not None:
        return float(record["kj"]) / KJ_PER_KCAL

    raise ProductError("record carries no energy value")


def product_from_record(record: dict) -> Product:
    """Read one pantry JSONL record. Nutrients are per 100 g, always."""
    values = {"kcal": _kcal(record)}
    for field in MACRO_KEYS[1:]:
        if record.get(field) is None:
            raise ProductError(f"record carries no {field}")
        values[field] = float(record[field])

    # Carried through when the record states them, and left unset otherwise:
    # pantry never infers a zero here, so neither does the snapshot.
    for field in OPTIONAL_NUTRIENT_KEYS:
        if record.get(field) is not None:
            values[field] = float(record[field])

    # `NaN` and `Infinity` are readable JSON, and every total goes through
    # `round_js`, which raises `ValueError` on the first and `OverflowError` on
    # the second. Unguarded, one field of one record is an unhandled traceback
    # from `resolve`; refused here, it is a refusal that names the field.
    for field, value in values.items():
        if not isfinite(value):
            raise ProductError(f"record has an unusable {field}: {value}")

    return Product(
        name=str(record.get("name") or ""),
        source=str(record.get("source") or ""),
        id=str(record.get("id") or ""),
        brand=str(record.get("brand") or ""),
        **values,
    )


def _search_results(results: list[dict]) -> list[dict]:
    """Translate Pantry search rows at the Recipes boundary.

    The four macros only: pantry's search rows zero an absent nutrient, and a
    browsing surface is not worth inventing a fibre figure for. A reference
    resolved through `lookup` reads the record itself and keeps what it says.
    """
    return [
        {
            "source": result.get("source"),
            "id": str(result.get("id")),
            "name": result.get("name", ""),
            "brand": result.get("brand") or "",
            "macros": {
                key: float(result.get("nutrients", {}).get(key, 0))
                for key in MACRO_KEYS
            },
        }
        for result in results
    ]


class PantryProducts:
    """Pantry's owned shards and user overlay behind ProductLookup."""

    def __init__(self, store: Store) -> None:
        self.store = store

    def lookup(self, source: str, id: str) -> Product | None:
        record = self.store.find(source, id)
        return product_from_record(record) if record is not None else None

    def search(
        self, query: str, limit: int = 10, remote: bool = False
    ) -> list[dict]:
        return _search_results(self.store.search(query, limit=limit))


class JsonlProducts:
    """Products read from pantry-format JSONL files, loaded on first use.

    A shard omits `source` because its filename supplies it; a combined asset
    carries it explicitly. Both forms are accepted.
    """

    def __init__(self, paths: list[Path]) -> None:
        self.paths = paths
        self._index: dict[tuple[str, str], Product] | None = None
        self._local: Any = None

    def _load(self) -> None:

        index: dict[tuple[str, str], Product] = {}
        raw_records: list[dict] = []

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
                raw_records.append(record)

        self._index = index
        self._local = Local(raw_records)

    def lookup(self, source: str, id: str) -> Product | None:
        if self._index is None:
            self._load()
        assert self._index is not None
        return self._index.get((source, id))

    def search(
        self, query: str, limit: int = 10, remote: bool = False
    ) -> list[dict]:
        if self._local is None:
            self._load()
        assert self._local is not None
        results = self._local.search(query, limit=limit)
        return _search_results(results)


def resolve_lookup(
    ctx: click.Context | None, directory: Path | None
) -> ProductLookup:
    """The injected lookup, an explicit export, or Pantry's local store."""
    if ctx is not None and ctx.obj is not None:
        return ctx.obj

    if directory is not None:
        return JsonlProducts(sorted(directory.glob("*.jsonl")))

    # Pantry's store is a directory of per-source shards, the same layout its
    # frozen data ships in.
    store = Store(
        lambda: pantry_data.read_shards(pantry_data.data_dir()),
        products_dir(),
    )
    return PantryProducts(store)
