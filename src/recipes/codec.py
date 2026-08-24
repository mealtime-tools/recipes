"""The share URL: a whole recipe, in a fragment, resolvable by nobody.

The page that renders one has no database and no network, so the payload
carries resolved names and nutrients instead of references. It lives in the
fragment rather than the query so the payload never reaches a server: it stays
out of Pages logs and referrers, and it escapes query-length limits.

Wire format (see SPEC): `base64url(raw_deflate(compact_json))`, `=` stripped.
The compressed JSON uses the same readable fields as every other component.
"""

import base64
import json
import zlib

from recipes.macros import (
    IncompleteRecipe,
    compact_number,
    parse_servings,
    unresolved,
)
from recipes.models import (
    MACRO_KEYS,
    OPTIONAL_NUTRIENT_KEYS,
    Ingredient,
    Macros,
    Recipe,
)

FRAGMENT_KEY = "r"

# Raw deflate: no zlib header, no checksum. Two bytes of header and four of
# Adler-32 are eight base64 characters that a QR code has to carry.
_WINDOW_BITS = -15


class ShareUrlError(ValueError):
    """A URL that does not carry a readable recipe."""


def payload_of(recipe: Recipe) -> dict:
    """Build the compact object. Key order is part of the wire format.

    Refuses an incomplete recipe rather than sharing the part of it that
    happens to be resolved: a link is the durable artefact, and one that
    quietly drops an ingredient understates every total forever.
    """
    errors = unresolved(recipe)
    if errors:
        raise IncompleteRecipe(recipe, errors)

    return {
        "name": recipe.name,
        "servings": parse_servings(recipe.servings),
        "notes": recipe.notes,
        "tags": list(recipe.tags),
        "ingredients": [_item_of(item) for item in recipe.ingredients],
    }


def _item_of(item: Ingredient) -> dict:
    """One readable ingredient using the shared nutrient shape."""
    macros = item.macros
    assert macros is not None, "payload_of refuses unresolved ingredients"

    return {
        "name": item.name or item.ref,
        "grams": compact_number(item.grams),
        **macros.stated(),
    }


def encode_payload(payload: dict) -> str:
    """Compress and encode one payload object."""
    text = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    deflate = zlib.compressobj(9, zlib.DEFLATED, _WINDOW_BITS)
    raw = deflate.compress(text.encode()) + deflate.flush()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_payload(encoded: str) -> dict:
    """Reverse `encode_payload`, restoring the padding base64 needs."""
    padded = encoded + "=" * (-len(encoded) % 4)
    try:
        raw = base64.urlsafe_b64decode(padded)
        text = zlib.decompress(raw, _WINDOW_BITS).decode()
        payload = json.loads(text)
    except Exception as exc:
        raise ShareUrlError(f"unreadable share payload: {exc}") from exc

    if not isinstance(payload, dict):
        raise ShareUrlError("share payload is not an object")

    return payload


def share_url(recipe: Recipe, base: str) -> str:
    """The one link that carries this recipe, under a caller-supplied base.

    `base` is passed in rather than known here: see `viewer.py` for why a data
    package must not carry a deployment address.
    """
    return f"{base}#{FRAGMENT_KEY}={encode_payload(payload_of(recipe))}"


def recipe_from_payload(payload: dict) -> Recipe:
    """Read a payload back into a recipe of `manual` ingredients.

    A shared link has no references to resolve, so its ingredients are named
    `manual` with the ingredient name as the id: honest about where the macros
    came from, and refreshable by nothing, which is correct.
    """
    rows = payload.get("ingredients") or []
    if not isinstance(rows, list):
        raise ShareUrlError("share payload ingredients are not a list")

    return Recipe(
        name=str(payload.get("name") or ""),
        servings=parse_servings(payload.get("servings", 1)),
        notes=str(payload.get("notes") or ""),
        tags=[str(tag) for tag in payload.get("tags") or []],
        ingredients=[_ingredient_from_item(row) for row in rows],
    )


def _ingredient_from_item(row: object) -> Ingredient:
    """Read one canonical ingredient, or refuse it.

    A short row is refused rather than padded with zeros: an inferred zero
    under-counts every total downstream and cannot be told from a real one.
    """
    if not isinstance(row, dict):
        raise ShareUrlError(f"malformed ingredient entry: {row!r}")

    try:
        name = str(row.get("name") or "Ingredient")
        grams = float(row["grams"])
        values = {key: float(row[key]) for key in MACRO_KEYS}
        values.update(
            {
                key: float(row[key])
                for key in OPTIONAL_NUTRIENT_KEYS
                if row.get(key) is not None
            }
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ShareUrlError(f"malformed ingredient entry: {row!r}") from exc

    return Ingredient(
        source="manual",
        id=name,
        grams=grams,
        name=name,
        macros=Macros(**values),
    )
