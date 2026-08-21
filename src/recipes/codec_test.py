"""The share payload, pinned to the cross-verified golden vectors.

A share URL is the durable artefact: one that a JavaScript decoder cannot read
byte for byte is a lost recipe. `codec-vectors.json` was generated once and
cross-checked against a JavaScript decoder, so it, not this code, is the
authority.
"""

import json
from pathlib import Path

import pytest

from recipes.codec import (
    decode_payload,
    encode_payload,
    payload_of,
    recipe_from_payload,
    share_url,
)
from recipes.models import Ingredient, Macros, Recipe

VECTORS = json.loads(
    (Path(__file__).resolve().parents[2] / "codec-vectors.json").read_text()
)
CASES = [pytest.param(case, id=case["label"]) for case in VECTORS["cases"]]


@pytest.mark.parametrize("case", CASES)
def test_encoder_reproduces_the_golden_vector(case: dict) -> None:
    assert encode_payload(case["payload"]) == case["encoded"]


@pytest.mark.parametrize("case", CASES)
def test_decoder_reads_the_golden_vector(case: dict) -> None:
    assert decode_payload(case["encoded"]) == case["payload"]


def test_recipe_encodes_to_the_pinned_payload() -> None:
    """The Recipe -> payload mapping, not just the compression.

    Amounts are whole numbers and macros are not, and the vectors pin that
    distinction: `60` and `258.0` are different bytes.
    """
    case = next(c for c in VECTORS["cases"] if c["label"] == "minimal")
    recipe = Recipe(
        name="Toast",
        ingredients=[
            Ingredient(
                source="coles",
                id="1",
                grams=60,
                name="Sourdough",
                macros=Macros(kcal=258.0, protein=9.1, fat=2.1, carbs=47.5),
            )
        ],
    )

    assert payload_of(recipe) == case["payload"]
    assert encode_payload(payload_of(recipe)) == case["encoded"]


def test_share_url_round_trips_a_whole_recipe() -> None:
    recipe = Recipe(
        name="Sourdough Pizza",
        servings=2,
        notes="Stretch cold, from the edges.\nBake 8 min at max heat.",
        ingredients=[
            Ingredient(
                source="coles",
                id="42:a",
                grams=475,
                name="Pizza Dough",
                macros=Macros(kcal=268.0, protein=8.9, fat=3.1, carbs=49.2),
            )
        ],
    )

    url = share_url(recipe, "https://recipes.example/")
    restored = recipe_from_payload(decode_payload(url.split("#r=")[1]))

    assert restored.name == recipe.name
    assert restored.servings == 2
    assert restored.notes == recipe.notes
    assert restored.ingredients[0].name == "Pizza Dough"
    assert restored.ingredients[0].grams == 475
    assert restored.ingredients[0].macros == recipe.ingredients[0].macros
