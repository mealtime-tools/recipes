"""Edit one recipe in a text editor or append one piped ingredient."""

import json
import math
from decimal import Decimal
from pathlib import Path
from typing import Any, TextIO

import click
from agentcli import UsageError, emit, json_option
from mealtime_nutrients import CORE_NUTRIENTS, NUTRIENTS

from recipes import store
from recipes.commands.shared import dir_option, refusing, resolve_dir
from recipes.models import (
    PRODUCT_SOURCES,
    Ingredient,
    Macros,
    Recipe,
    to_decimal,
)
from recipes.render import describe


def _input_item(stream: TextIO) -> dict[str, Any]:
    try:
        item = json.load(stream)
    except json.JSONDecodeError as exc:
        raise UsageError(f"input is not valid JSON: {exc}") from exc
    if not isinstance(item, dict):
        raise UsageError("input must contain one JSON object")
    if isinstance(item.get("data"), dict):
        item = item["data"]
    candidates = item.get("candidates")
    if isinstance(candidates, list) and len(candidates) == 1:
        item = candidates[0]
    if isinstance(item.get("product"), dict):
        item = item["product"]
    return item


def _grams(item: dict[str, Any]) -> float:
    """The weight the piped nutrients describe. Never inferred."""
    stated = item.get("grams")
    if stated is None:
        raise UsageError(
            "input states no grams: state the weight these figures "
            "describe; to record a different portion, scale the figures "
            "to it or add the ingredient by reference and run resolve"
        )

    if (
        isinstance(stated, bool)
        or not isinstance(stated, (int, float))
        or not math.isfinite(stated)
        or stated <= 0
    ):
        raise UsageError("grams must be a positive finite number")

    return float(stated)


def _ingredient(item: dict[str, Any]) -> Ingredient:
    missing = [key for key in CORE_NUTRIENTS if item.get(key) is None]
    if missing:
        raise UsageError(f"input nutrients missing {', '.join(missing)}")

    values: dict[str, Decimal] = {}
    for key in NUTRIENTS:
        value = item.get(key)
        # Left out rather than stored as a null: `Macros` reads both the same.
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise UsageError(f"{key} must be a number or null")
        if not math.isfinite(value) or value < 0:
            raise UsageError(f"{key} must be non-negative and finite")
        values[key] = to_decimal(value)

    source = str(item.get("source") or "manual")
    if source not in PRODUCT_SOURCES:
        source = "manual"
    name = str(item.get("name") or item.get("title") or "Ingredient")
    return Ingredient(
        source=source,
        id=str(item.get("id") or name),
        grams=_grams(item),
        name=name,
        macros=Macros(**values),
    )


@click.command("edit")
@click.argument("name")
@click.option(
    "--input",
    "input_file",
    type=click.File("r", encoding="utf-8"),
    help="Append one JSON item from PATH, or '-' for stdin.",
)
@dir_option
@json_option
@refusing
def edit(
    name: str,
    input_file: TextIO | None,
    directory: Path | None,
    json_output: bool,
) -> None:
    """Edit NAME, creating a minimal YAML recipe when it does not exist."""
    root = resolve_dir(directory)
    # Read before anything is written, so a refusal leaves the directory as is.
    appended = None
    if input_file is not None:
        appended = _ingredient(_input_item(input_file))

    stored = store.find(root, name)
    path = stored.path if stored else store.path_for(root, name)

    if appended is not None:
        recipe = stored.recipe if stored else Recipe(name=name)
        recipe.ingredients.append(appended)
        store.write(path, recipe)
        emit(
            {**describe(recipe), "path": str(path)},
            json_output=json_output,
            human=lambda result: [result["path"]],
        )
        return

    if stored is None:
        store.write(path, Recipe(name=name))

    click.edit(filename=str(path))
    recipe = store.load_recipe(path)
    emit(
        {"name": recipe.name, "path": str(path)},
        json_output=json_output,
        human=lambda result: [result["path"]],
    )
