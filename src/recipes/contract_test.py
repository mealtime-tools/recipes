"""Small tests for the behavior other tools rely on."""

import json
import os
import subprocess
import sys
from pathlib import Path

import yaml
from click.testing import CliRunner

from recipes.cli import main
from recipes.codec import decode_payload, encode_payload, share_url
from recipes.models import Ingredient, Macros, Recipe
from recipes.products import product_from_record
from recipes.render import describe
from recipes.store import load_recipe, write
from recipes.viewer import DEFAULT_VIEWER_URL, ENV_VAR, viewer_url

_PRINT_VIEWER_URL = (
    "from recipes.viewer import viewer_url; print(viewer_url())"
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


def test_viewer_url_ignores_a_dotenv_on_the_cwd_discovery_branch(
    tmp_path: Path,
) -> None:
    # python-dotenv resolves `.env` from the working directory only on its
    # interactive branch, which a `-c` invocation takes. An installed console
    # script takes the other branch and walks up from the package directory
    # instead, which is the path that retargeted links in the reported bug.
    # This covers the cwd branch, the half that is cheap to reach hermetically;
    # `test_resolving_the_viewer_url_never_loads_a_dotenv_file` guards the
    # other half, which would otherwise need a throwaway install.
    (tmp_path / ".env").write_text(f"{ENV_VAR}=https://stale.test/plate/\n")
    workdir = tmp_path / "recipes"
    workdir.mkdir()
    env = {k: v for k, v in os.environ.items() if k != ENV_VAR}

    printed = subprocess.run(
        [sys.executable, "-c", _PRINT_VIEWER_URL],
        cwd=workdir,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    assert printed == DEFAULT_VIEWER_URL


def test_resolving_the_viewer_url_never_loads_a_dotenv_file() -> None:
    # The bug was install-dir-relative: the upward walk started at the package
    # directory, so a `.env` above the install location retargeted every link
    # regardless of the working directory. Relocating the package to reproduce
    # that needs a throwaway install, so assert the root cause instead --
    # resolving the URL must not reach python-dotenv at all.
    probe = "import recipes.viewer, sys; print('dotenv' in sys.modules)"
    printed = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    assert printed == "False"


def test_viewer_url_reads_the_process_environment() -> None:
    assert viewer_url({ENV_VAR: "https://mine.test/plate/"}) == (
        "https://mine.test/plate/"
    )
    assert viewer_url({ENV_VAR: "  "}) == DEFAULT_VIEWER_URL
    assert viewer_url({}) == DEFAULT_VIEWER_URL


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
