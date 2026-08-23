"""Small tests for the behavior other tools rely on."""

import json
from pathlib import Path

import yaml
from click.testing import CliRunner, Result

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


def _append(tmp_path: Path, item: dict, *json_flag: str) -> Result:
    return CliRunner().invoke(
        main,
        [
            "edit",
            "Pancakes",
            "--dir",
            str(tmp_path),
            "--input",
            "-",
            *json_flag,
        ],
        input=json.dumps(item),
    )


def test_edit_reports_nutrients_outweighing_the_portion_in_json(
    tmp_path: Path,
) -> None:
    """The reported failure: per-100 g figures beside a real portion weight.

    The victim consumes `--json`, so the warning has to be in the payload;
    on stderr it would not reach them.
    """
    result = _append(
        tmp_path,
        {
            "name": "Buckwheat flour",
            "grams": 42,
            "kcal": 364,
            "protein": 13.2,
            "fat": 3.4,
            "carbs": 69.0,
        },
        "--json",
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)["data"]
    assert len(payload["warnings"]) == 1, payload["warnings"]
    assert "42 g" in payload["warnings"][0]
    # Warning, not refusal, and the numbers are stored as given: which of the
    # two the caller meant to change is not something this command can know.
    assert load_recipe(Path(payload["path"])).ingredients[0].macros.kcal == 364


def test_edit_reports_energy_no_macronutrient_can_account_for(
    tmp_path: Path,
) -> None:
    """Alcohol carries energy the macro masses cannot bound. AFCD ships it."""
    result = _append(
        tmp_path,
        {
            "name": "Vodka",
            "grams": 20,
            "kcal": 213.2,
            "protein": 0,
            "fat": 0,
            "carbs": 0.1,
        },
        "--json",
    )

    assert result.exit_code == 0, result.output
    warnings = json.loads(result.stdout)["data"]["warnings"]
    assert len(warnings) == 1, warnings
    assert "kcal" in warnings[0]


def test_edit_reports_no_warnings_for_nutrients_that_fit_the_portion(
    tmp_path: Path,
) -> None:
    """Correctly scaled values, and a 1.6 g portion where rounding dominates."""
    fitting = (
        {
            "name": "Buckwheat flour",
            "grams": 42,
            "kcal": 153,
            "protein": 5.5,
            "fat": 1.4,
            "carbs": 29.0,
        },
        # Real leaf gelatine: one sheet, rounded to a tenth of a gram.
        {
            "name": "Gelatine leaf",
            "grams": 1.6,
            "kcal": 6,
            "protein": 1.7,
            "fat": 0,
            "carbs": 0,
        },
    )

    for item in fitting:
        result = _append(tmp_path, item, "--json")

        assert result.exit_code == 0, result.output
        payload = json.loads(result.stdout)["data"]
        assert payload["warnings"] == [], (item, payload["warnings"])


def test_edit_keeps_human_stdout_to_the_path_and_warns_on_stderr(
    tmp_path: Path,
) -> None:
    """Without `--json`, stdout stays the one path a shell can consume."""
    result = _append(
        tmp_path,
        {
            "name": "Buckwheat flour",
            "grams": 42,
            "kcal": 364,
            "protein": 13.2,
            "fat": 3.4,
            "carbs": 69.0,
        },
    )

    assert result.exit_code == 0, result.output
    assert result.stdout.strip().endswith(".yaml")
    assert "42 g" in result.stderr, result.stderr


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
