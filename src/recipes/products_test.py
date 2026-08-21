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
            "carbs": 60.0,
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
                "carbs": 60.0,
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
                "carbs": 50.0,
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
