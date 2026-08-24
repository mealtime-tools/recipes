"""Small tests for the behavior other tools rely on."""

import dataclasses
import json
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner
from mealtime_nutrients import CORE_NUTRIENTS, NUTRIENTS

from recipes.cli import main
from recipes.codec import (
    ShareUrlError,
    decode_payload,
    encode_payload,
    payload_of,
    recipe_from_payload,
    share_url,
)
from recipes.models import Ingredient, Macros, Product, Recipe
from recipes.products import ProductError, product_from_record
from recipes.render import describe, macro_summary
from recipes.resolve import resolve_recipe
from recipes.store import StoreError, dump_recipe, load_recipe, write

# Spelled out, not imported: a test sharing the constant cannot catch a reorder.
# The first seven are the order every share link made before the vocabulary
# widened; the rest are alphabetical and were appended, never inserted.
WIRE_NUTRIENT_KEYS = [
    "kcal",
    "protein",
    "fat",
    "carbs",
    "fiber",
    "sodium",
    "sugar",
    "biotin",
    "caffeine",
    "calcium",
    "chloride",
    "cholesterol",
    "chromium",
    "copper",
    "folate",
    "folic_acid",
    "iodine",
    "iron",
    "magnesium",
    "manganese",
    "molybdenum",
    "monounsaturated_fat",
    "niacin",
    "pantothenic_acid",
    "phosphorus",
    "polyunsaturated_fat",
    "potassium",
    "riboflavin",
    "saturated_fat",
    "selenium",
    "thiamin",
    "trans_fat",
    "unsaturated_fat",
    "vitamin_a",
    "vitamin_b12",
    "vitamin_b6",
    "vitamin_c",
    "vitamin_d",
    "vitamin_e",
    "vitamin_k",
    "zinc",
]


def _pinned_recipe() -> Recipe:
    """One recipe covering both a fully stated and a partly stated snapshot."""
    return Recipe(
        name="Toast",
        servings=2,
        tags=["breakfast"],
        notes="Toast it.",
        ingredients=[
            Ingredient(
                source="manual",
                id="sourdough",
                grams=60,
                name="Sourdough",
                macros=Macros(
                    kcal=258,
                    protein=9.1,
                    fat=2.1,
                    carbs=47.5,
                    fiber=2.4,
                    sodium=0.5,
                    sugar=1.2,
                ),
            ),
            Ingredient(
                source="manual",
                id="butter",
                grams=10,
                name="Butter",
                macros=Macros(kcal=74, protein=0.1, fat=8.1, carbs=0),
            ),
        ],
    )


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

    stated = product.nutrients.as_dict()
    assert stated["carbs"] == 0
    assert stated["fiber"] is None
    assert product.macros(45).as_dict()["protein"] == 0


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
    assert description["calcium"] is None
    assert description["grams"] == 100
    assert "nutrients" not in description
    assert "macros" not in description


def test_recipe_yaml_omits_an_unstated_nutrient(tmp_path: Path) -> None:
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

    assert "fiber" not in raw["ingredients"][0]
    assert raw["ingredients"][0]["kcal"] == 0
    assert load_recipe(path) == recipe


def test_recipe_yaml_still_reads_an_explicit_null(tmp_path: Path) -> None:
    """Files written before nulls were omitted read the same as new ones."""
    path = tmp_path / "old.yaml"
    path.write_text(
        "name: Water\n"
        "servings: 1\n"
        "ingredients:\n"
        "- source: manual\n"
        "  id: water\n"
        "  grams: 100\n"
        "  kcal: 0\n"
        "  protein: 0\n"
        "  fat: 0\n"
        "  carbs: 0\n"
        "  fiber: null\n"
    )

    macros = load_recipe(path).ingredients[0].macros

    assert macros is not None
    assert macros.as_dict()["fiber"] is None
    assert macros.as_dict()["carbs"] == 0


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
    assert ingredient.macros.as_dict()["protein"] == 20


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
    assert ingredient.macros.as_dict()["kcal"] == 153


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
    assert ingredient.macros.as_dict()["kcal"] == 356


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


def test_human_summary_prints_only_the_stated_nutrients() -> None:
    """37 question marks is not a report; a stated figure is."""
    summary = macro_summary(describe(_pinned_recipe()))

    assert summary == "kcal 166  protein 4.6  fat 5.1  carbs 23.75"


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


def test_macros_as_dict_key_order_is_the_wire_format() -> None:
    macros = Macros(kcal=1, protein=2, fat=3, carbs=4)

    assert list(macros.as_dict()) == WIRE_NUTRIENT_KEYS


def test_the_vocabulary_is_the_shared_one() -> None:
    """Every name the tools exchange is carryable, and no name is invented."""
    assert set(WIRE_NUTRIENT_KEYS) == set(NUTRIENTS)
    assert WIRE_NUTRIENT_KEYS[: len(CORE_NUTRIENTS)] == list(CORE_NUTRIENTS)


def test_a_widened_nutrient_round_trips_through_both_formats(
    tmp_path: Path,
) -> None:
    """A name that only arrived with the wider vocabulary is carried too."""
    recipe = Recipe(
        name="Milk",
        ingredients=[
            Ingredient(
                source="manual",
                id="milk",
                grams=100,
                name="Milk",
                macros=Macros(
                    kcal=42, protein=3.4, fat=1, carbs=5, calcium=0.12
                ),
            )
        ],
    )
    path = tmp_path / "milk.yaml"
    write(path, recipe)

    assert load_recipe(path) == recipe
    stored = yaml.safe_load(path.read_text())["ingredients"][0]
    assert stored["calcium"] == 0.12
    assert "zinc" not in stored

    row = payload_of(recipe)["ingredients"][0]
    assert row["calcium"] == 0.12
    assert "zinc" not in row


def test_macros_requires_the_four_arithmetic_nutrients() -> None:
    with pytest.raises(TypeError):
        Macros(kcal=1, protein=2, fat=3)  # type: ignore[call-arg]


def test_macros_is_a_frozen_snapshot() -> None:
    macros = Macros(kcal=1, protein=2, fat=3, carbs=4)

    with pytest.raises(dataclasses.FrozenInstanceError):
        macros.kcal = 99  # type: ignore[misc]

    # By copy: editing what was handed out must not reach into the snapshot.
    borrowed = macros.as_dict()
    borrowed["kcal"] = 99
    assert macros.as_dict()["kcal"] == 1


def test_share_payload_json_is_byte_identical() -> None:
    payload = payload_of(_pinned_recipe())

    # No version field, so the exact text is the compatibility test.
    assert json.dumps(payload, separators=(",", ":")) == (
        '{"name":"Toast","servings":2,"notes":"Toast it.",'
        '"tags":["breakfast"],'
        '"ingredients":['
        '{"name":"Sourdough","grams":60,"kcal":258,"protein":9.1,"fat":2.1,'
        '"carbs":47.5,"fiber":2.4,"sodium":0.5,"sugar":1.2},'
        '{"name":"Butter","grams":10,"kcal":74,"protein":0.1,"fat":8.1,'
        '"carbs":0}]}'
    )
    assert decode_payload(encode_payload(payload)) == payload


def test_share_payload_still_reads_an_explicit_null() -> None:
    """Links made before nulls were omitted read the same as new ones."""
    row = {
        "name": "Butter",
        "grams": 10,
        "kcal": 74,
        "protein": 0.1,
        "fat": 8.1,
        "carbs": 0,
        "fiber": None,
    }

    recipe = recipe_from_payload({"name": "X", "ingredients": [row]})
    macros = recipe.ingredients[0].macros

    assert macros is not None
    assert macros.as_dict()["fiber"] is None
    assert macros.as_dict()["carbs"] == 0


def test_recipe_yaml_is_byte_identical() -> None:
    assert dump_recipe(_pinned_recipe()) == (
        "name: Toast\n"
        "servings: 2\n"
        "tags:\n"
        "- breakfast\n"
        "notes: Toast it.\n"
        "ingredients:\n"
        "- source: manual\n"
        "  id: sourdough\n"
        "  grams: 60\n"
        "  name: Sourdough\n"
        "  kcal: 258\n"
        "  protein: 9.1\n"
        "  fat: 2.1\n"
        "  carbs: 47.5\n"
        "  fiber: 2.4\n"
        "  sodium: 0.5\n"
        "  sugar: 1.2\n"
        "- source: manual\n"
        "  id: butter\n"
        "  grams: 10\n"
        "  name: Butter\n"
        "  kcal: 74\n"
        "  protein: 0.1\n"
        "  fat: 8.1\n"
        "  carbs: 0\n"
    )


def test_product_scales_every_nutrient_it_states() -> None:
    record = {
        "name": "Oats",
        "grams": 50,
        "kcal": 100,
        "protein": 8,
        "fat": 4,
        "carbs": 20,
        "fiber": 2,
        "sodium": 0.4,
        "sugar": 1.6,
    }

    # Every nutrient scales, so a forgotten one shows up as a wrong number.
    assert product_from_record(record).macros(125).stated() == {
        "kcal": 250,
        "protein": 20,
        "fat": 10,
        "carbs": 50,
        "fiber": 5,
        "sodium": 1.0,
        "sugar": 4.0,
    }


def test_product_scaling_leaves_an_unstated_nutrient_unstated() -> None:
    record = {
        "name": "Oats",
        "grams": 50,
        "kcal": 100,
        "protein": 8,
        "fat": 4,
        "carbs": 20,
        "fiber": 2,
    }

    scaled = product_from_record(record).macros(125).as_dict()

    assert scaled["fiber"] == 5
    assert scaled["sodium"] is None
    assert scaled["sugar"] is None


def test_a_record_stating_only_kilojoules_is_refused() -> None:
    """kcal is the wire vocabulary's only energy name; kJ is pantry's job."""
    record = {
        "name": "Oats",
        "grams": 100,
        "kj": 1500,
        "protein": 8,
        "fat": 4,
        "carbs": 20,
    }

    with pytest.raises(ProductError):
        product_from_record(record)

    # A record carrying both is unaffected: the extra key is simply not read.
    both = product_from_record({**record, "kcal": 359})
    assert both.nutrients.as_dict()["kcal"] == 359


def test_product_without_a_weight_scales_from_one_hundred_grams() -> None:
    product = product_from_record(
        {"name": "Oats", "kcal": 100, "protein": 8, "fat": 4, "carbs": 20}
    )

    assert product.macros().as_dict()["kcal"] == 100
    assert product.macros(50).as_dict()["kcal"] == 50


class _FakeLookup:
    """A lookup returning one product, for pinning resolve's change report."""

    def __init__(self, product: Product) -> None:
        self.product = product

    def lookup(self, source: str, id: str) -> Product | None:
        return self.product


def test_resolve_reports_a_changed_optional_nutrient_per_key() -> None:
    recipe = Recipe(
        name="Oats",
        ingredients=[
            Ingredient(
                source="manual",
                id="oats",
                grams=100,
                name="Oats",
                macros=Macros(kcal=100, protein=8, fat=4, carbs=20),
            )
        ],
    )
    lookup = _FakeLookup(
        product_from_record(
            {
                "name": "Oats",
                "grams": 100,
                "kcal": 100,
                "protein": 8,
                "fat": 4,
                "carbs": 20,
                "fiber": 9,
            }
        )
    )

    outcome = resolve_recipe(recipe, lookup, force=True)

    assert outcome.changes == [
        {
            "ref": "manual:oats",
            "name": "Oats",
            "fields": {"fiber": {"before": None, "after": 9.0}},
        }
    ]
