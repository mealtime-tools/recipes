"""Small tests for the behavior other tools rely on."""

import json
from pathlib import Path

import yaml
from click.testing import CliRunner

from recipes.cli import main
from recipes.codec import decode_payload, encode_payload, share_url
from recipes.models import Ingredient, Macros, Recipe
from recipes.products import product_from_record
from recipes.render import describe
from recipes.store import load_recipe, write


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


def test_edit_warns_when_nutrients_outweigh_the_portion(
    tmp_path: Path,
) -> None:
    """Per-100 g figures pasted beside a real portion weight, the usual trap."""
    item = {
        "name": "Buckwheat flour",
        "grams": 42,
        "kcal": 364,
        "protein": 13.2,
        "fat": 3.4,
        "carbs": 69.0,
    }
    result = CliRunner().invoke(
        main,
        ["edit", "Pancakes", "--dir", str(tmp_path), "--input", "-", "--json"],
        input=json.dumps(item),
    )

    assert result.exit_code == 0, result.output
    assert "100 g" in result.stderr, result.stderr
    # The warning informs, it never blocks, and `--json` keeps stdout to one
    # object: the item is still appended exactly as it was given.
    payload = json.loads(result.stdout)["data"]
    assert load_recipe(Path(payload["path"])).ingredients[0].macros.kcal == 364


def test_edit_stays_quiet_when_nutrients_fit_the_portion(
    tmp_path: Path,
) -> None:
    item = {
        "name": "Buckwheat flour",
        "grams": 42,
        "kcal": 153,
        "protein": 5.5,
        "fat": 1.4,
        "carbs": 29.0,
    }
    result = CliRunner().invoke(
        main,
        ["edit", "Pancakes", "--dir", str(tmp_path), "--input", "-", "--json"],
        input=json.dumps(item),
    )

    assert result.exit_code == 0, result.output
    assert result.stderr == ""


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
