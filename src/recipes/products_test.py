"""The default product reader: pantry-format JSONL, read never written."""

import json

import pytest

from recipes.models import Ingredient, Recipe
from recipes.products import JsonlProducts, ProductError, resolve_lookup
from recipes.resolve import resolve_recipe


def shard(tmp_path, *records: dict):
    """A source shard: its filename supplies the source, as pantry does."""
    path = tmp_path / "coles.jsonl"
    path.write_text("\n".join(json.dumps(record) for record in records) + "\n")
    return JsonlProducts([path])


def test_the_filename_supplies_the_source_and_kj_supplies_kcal(
    tmp_path,
) -> None:
    """Records carry kJ; a recipe needs kcal, and the conversion is exact."""
    lookup = shard(
        tmp_path,
        {
            "id": "01",
            "name": "Rolled Oats",
            "kj": 1569.0,
            "fat": 8.0,
            "carbohydrates": 60.0,
            "protein": 13.0,
        },
    )

    product = lookup.lookup("coles", "01")

    assert product.name == "Rolled Oats"
    assert round(product.kcal, 2) == 375.0
    # A leading-zero id is not the integer 1.
    assert lookup.lookup("coles", "1") is None


def test_a_record_missing_a_macro_is_refused_by_name(tmp_path) -> None:
    """Never inferred as zero, and the failure names the reference."""
    lookup = shard(tmp_path, {"id": "2", "name": "Mystery", "kcal": 100.0})

    with pytest.raises(ProductError):
        lookup.lookup("coles", "2")

    recipe = Recipe(
        name="Mystery",
        ingredients=[Ingredient(source="coles", id="2", grams=100.0)],
    )

    assert resolve_recipe(recipe, lookup).errors == [
        "coles:2: record carries no protein"
    ]


def test_a_record_that_states_fibre_and_sugar_keeps_them(tmp_path) -> None:
    """The seam issue #1 is about: pantry knows, so the snapshot must too."""
    lookup = shard(
        tmp_path,
        {
            "id": "3",
            "name": "Soy Milk",
            "kcal": 42.0,
            "protein": 3.0,
            "fat": 1.6,
            "carbohydrates": 3.3,
            "dietary_fiber": 0.2,
            "sugar": 1.0,
        },
    )

    product = lookup.lookup("coles", "3")

    assert (product.dietary_fiber, product.sugar) == (0.2, 1.0)
    assert product.macros().as_dict()["dietary_fiber"] == 0.2


def test_a_stated_zero_survives_and_an_unstated_nutrient_stays_unstated(
    tmp_path,
) -> None:
    """The common case in the shipped shards: `dietary_fiber: 0` is a measurement.

    Two in five AFCD records state a zero fibre. Reading them as unstated
    would throw away most of what this seam was widened to carry, and reading
    an unstated nutrient as zero would invent a measurement.
    """
    lookup = shard(
        tmp_path,
        {
            "id": "4",
            "name": "Rice Syrup",
            "kcal": 316.0,
            "protein": 0.2,
            "fat": 0.0,
            "carbohydrates": 78.0,
            "dietary_fiber": 0,
        },
    )

    product = lookup.lookup("coles", "4")

    assert product.dietary_fiber == 0.0
    assert product.sugar is None
    assert "dietary_fiber" in product.macros().as_dict()
    assert "sugar" not in product.macros().as_dict()


def test_search_rows_carry_the_four_macros_only(tmp_path) -> None:
    """A picker row zeroes what it does not know, so it carries no nutrient
    this package would have to guess about."""
    lookup = shard(
        tmp_path,
        {
            "id": "5",
            "name": "Rolled Oats",
            "kcal": 375.0,
            "protein": 13.0,
            "fat": 8.0,
            "carbohydrates": 60.0,
            "dietary_fiber": 10.1,
        },
    )

    [row] = lookup.search("oats")

    assert set(row["macros"]) == {"kcal", "protein", "fat", "carbohydrates"}


@pytest.mark.parametrize(
    ("field", "value"),
    [
        # The optional nutrient, in both spellings a total cannot survive.
        ("dietary_fiber", float("nan")),
        ("dietary_fiber", float("inf")),
        # And a required macro: the rule is about every nutrient, not the two
        # this file learned to read most recently.
        ("kcal", float("nan")),
        ("protein", float("-inf")),
    ],
)
def test_a_record_whose_nutrient_is_not_finite_is_refused(
    tmp_path, field: str, value: float
) -> None:
    """`NaN` and `Infinity` are readable JSON that no total survives."""
    record = {
        "id": "6",
        "name": "Broken",
        "kcal": 100.0,
        "protein": 1.0,
        "fat": 1.0,
        "carbohydrates": 1.0,
    }
    lookup = shard(tmp_path, {**record, field: value})

    with pytest.raises(ProductError, match=f"unusable {field}"):
        lookup.lookup("coles", "6")


def test_default_lookup_combines_owned_and_user_shards(
    tmp_path, monkeypatch
) -> None:
    """Serve must re-resolve frozen products without an export directory."""
    owned = tmp_path / "owned"
    owned.mkdir()
    (owned / "coles.jsonl").write_text(
        json.dumps(
            {
                "id": "1",
                "name": "Frozen Oats",
                "brand": "Example",
                "kcal": 375.0,
                "protein": 13.0,
                "fat": 8.0,
                "carbohydrates": 60.0,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    config = tmp_path / "config" / "pantry"
    config.mkdir(parents=True)
    # The user's own records use the same layout as the frozen shards: one
    # file per source, the row taking its source from the filename.
    (config / "usda.jsonl").write_text(
        json.dumps(
            {
                "id": "2",
                "name": "User Flour",
                "brand": "Example",
                "kcal": 367.0,
                "protein": 33.33,
                "fat": 3.33,
                "carbohydrates": 50.0,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr("recipes.products.pantry_data.data_dir", lambda: owned)
    monkeypatch.setattr("recipes.products.products_dir", lambda: config)

    lookup = resolve_lookup(None, None)

    assert lookup.lookup("coles", "1").name == "Frozen Oats"
    assert lookup.lookup("usda", "2").name == "User Flour"
