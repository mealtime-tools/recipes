"""Small tests for the behavior other tools rely on."""

import json
from pathlib import Path

import yaml
from click.testing import CliRunner

from recipes.cli import main
from recipes.codec import (
    ShareUrlError,
    decode_payload,
    encode_payload,
    recipe_from_payload,
    share_url,
)
from recipes.models import Ingredient, Macros, Recipe
from recipes.products import product_from_record
from recipes.render import describe
from recipes.store import StoreError, load_recipe, write


def test_product_records_accept_canonical_names_and_preserve_zero() -> None:
    product = product_from_record(
        {
            "name": "Water",
            "grams": 90,
            "kcal": 0,
            "protein": 0,
            "fat": 0,
            "carbs": 0,
            "fiber": None,
        }
    )

    assert product.carbs == 0
    assert product.fiber is None
    assert product.macros(45).protein == 0


def test_recipe_output_uses_null_for_unknown_and_zero_for_zero() -> None:
    recipe = Recipe(
        name="Water",
        ingredients=[
            Ingredient(
                source="manual",
                id="water",
                grams=100,
                macros=Macros(kcal=0, protein=0, fat=0, carbs=0),
            )
        ],
    )

    description = describe(recipe)
    assert description["kcal"] == 0
    assert description["fiber"] is None
    assert description["grams"] == 100
    assert "nutrients" not in description
    assert "macros" not in description


def test_recipe_yaml_round_trip_keeps_nulls(tmp_path: Path) -> None:
    path = tmp_path / "water.yaml"
    recipe = Recipe(
        name="Water",
        ingredients=[
            Ingredient(
                source="manual",
                id="water",
                grams=100,
                macros=Macros(kcal=0, protein=0, fat=0, carbs=0),
            )
        ],
    )

    write(path, recipe)
    raw = yaml.safe_load(path.read_text())

    assert raw["ingredients"][0]["fiber"] is None
    assert load_recipe(path) == recipe


def test_edit_creates_a_recipe_file(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        main,
        ["edit", "Bean salad", "--dir", str(tmp_path), "--json"],
        env={"EDITOR": "true"},
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)["data"]
    assert Path(payload["path"]).is_file()
    assert load_recipe(Path(payload["path"])).name == "Bean salad"


def test_edit_appends_a_piped_item(tmp_path: Path) -> None:
    item = {
        "ok": True,
        "data": {
            "id": "bar",
            "name": "Protein bar",
            "grams": 50,
            "kcal": 200,
            "protein": 20,
            "fat": 5,
            "carbs": 15,
        },
    }
    result = CliRunner().invoke(
        main,
        [
            "edit",
            "Snacks",
            "--dir",
            str(tmp_path),
            "--input",
            "-",
            "--json",
        ],
        input=json.dumps(item),
    )

    assert result.exit_code == 0, result.output
    ingredient = load_recipe(
        Path(json.loads(result.output)["data"]["path"])
    ).ingredients[0]
    assert ingredient.macros.protein == 20


def _edit_input(tmp_path: Path, item: dict, *args: str) -> object:
    return CliRunner().invoke(
        main,
        ["edit", "Snacks", "--dir", str(tmp_path), "--input", "-", "--json"]
        + list(args),
        input=json.dumps(item),
    )


def test_edit_refuses_an_item_that_states_no_basis(tmp_path: Path) -> None:
    result = _edit_input(
        tmp_path,
        {"name": "Tofu", "kcal": 364, "protein": 8, "fat": 4, "carbs": 4},
    )

    assert result.exit_code != 0, result.output
    assert not json.loads(result.output)["ok"]


def test_refused_input_leaves_the_directory_untouched(tmp_path: Path) -> None:
    """A refusal writes nothing: no stub recipe, and no edit to an existing."""
    unusable = {
        "name": "Tofu",
        "kcal": 364,
        "protein": 8,
        "fat": 4,
        "carbs": 4,
    }

    assert _edit_input(tmp_path, unusable).exit_code != 0
    assert list(tmp_path.iterdir()) == []

    usable = {**unusable, "grams": 100}
    assert _edit_input(tmp_path, usable).exit_code == 0
    before = {path: path.read_bytes() for path in tmp_path.iterdir()}

    assert _edit_input(tmp_path, unusable).exit_code != 0
    assert {path: path.read_bytes() for path in tmp_path.iterdir()} == before


def test_edit_honours_a_stated_weight(tmp_path: Path) -> None:
    result = _edit_input(
        tmp_path,
        {
            "name": "Tofu",
            "grams": 42,
            "kcal": 153,
            "protein": 3.4,
            "fat": 1.7,
            "carbs": 1.7,
        },
    )

    assert result.exit_code == 0, result.output
    ingredient = load_recipe(
        Path(json.loads(result.output)["data"]["path"])
    ).ingredients[0]
    assert ingredient.grams == 42
    assert ingredient.macros.kcal == 153


def test_edit_refuses_an_explicit_null_weight(tmp_path: Path) -> None:
    """A stated null is no more a basis than a missing key is."""
    result = _edit_input(
        tmp_path,
        {
            "name": "Tofu",
            "grams": None,
            "kcal": 364,
            "protein": 8,
            "fat": 4,
            "carbs": 4,
        },
    )

    assert result.exit_code != 0, result.output


def test_edit_appends_an_eatout_meal_given_a_weight(tmp_path: Path) -> None:
    """An eatout item is appendable, but only once weighed."""
    meal = {
        "ok": True,
        "data": {
            "candidates": [
                {
                    "kind": "meal",
                    "id": "cali-press-the-shredder-smoothie-regular",
                    "name": "Cali Press - The Shredder Smoothie (Regular)",
                    "kcal": 356,
                    "protein": 31.8,
                    "fat": 14.4,
                    "carbs": 23.2,
                    "fiber": None,
                }
            ]
        },
    }
    weighed = dict(meal)
    weighed["data"] = {"candidates": [{**meal["data"]["candidates"][0]}]}
    weighed["data"]["candidates"][0]["grams"] = 350

    assert _edit_input(tmp_path, meal).exit_code != 0
    result = _edit_input(tmp_path, weighed)

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)["data"]
    assert payload["grams"] == 350
    ingredient = load_recipe(Path(payload["path"])).ingredients[0]
    assert ingredient.grams == 350
    assert ingredient.macros.kcal == 356


def test_stored_ingredient_needs_a_stated_weight(tmp_path: Path) -> None:
    """Neither an absent `grams` nor a null one reaches the arithmetic."""
    head = "name: Smoothie\ningredients:\n- source: manual\n  id: x\n"
    nutrients = "  kcal: 1\n  protein: 1\n  fat: 1\n  carbs: 1\n"

    for weight in ("", "  grams: null\n"):
        path = tmp_path / "meal.yaml"
        path.write_text(head + weight + nutrients)
        try:
            load_recipe(path)
        except StoreError:
            continue
        raise AssertionError(f"an unstated weight must be refused: {weight!r}")


def test_shared_ingredient_needs_a_stated_weight() -> None:
    """The third ingress refuses the same two shapes the other two do."""
    nutrients = {"kcal": 1, "protein": 1, "fat": 1, "carbs": 1}

    for row in ({**nutrients}, {**nutrients, "grams": None}):
        try:
            recipe_from_payload({"name": "X", "ingredients": [row]})
        except ShareUrlError:
            continue
        raise AssertionError(f"an unstated weight must be refused: {row!r}")


def test_every_stored_weight_is_a_number_the_arithmetic_can_use(
    tmp_path: Path,
) -> None:
    """The one shape `render` and `share` may ever see is a real weight."""
    recipe = Recipe(
        name="Toast",
        ingredients=[
            Ingredient(
                source="manual",
                id="toast",
                grams=60,
                macros=Macros(kcal=258, protein=9.1, fat=2.1, carbs=47.5),
            )
        ],
    )
    path = tmp_path / "toast.yaml"
    write(path, recipe)

    for item in load_recipe(path).ingredients:
        assert isinstance(item.grams, float)

    assert describe(recipe)["grams"] == 60


def test_share_codec_round_trips_current_format() -> None:
    recipe = Recipe(
        name="Toast",
        ingredients=[
            Ingredient(
                source="manual",
                id="toast",
                grams=60,
                name="Sourdough",
                macros=Macros(kcal=258, protein=9.1, fat=2.1, carbs=47.5),
            )
        ],
    )

    encoded = share_url(recipe, "https://example.test/").split("#r=")[1]
    assert encode_payload(decode_payload(encoded)) == encoded
