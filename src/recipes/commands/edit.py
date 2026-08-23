"""Edit one recipe in a text editor or append one piped ingredient."""

import json
import math
from pathlib import Path
from typing import Any, TextIO

import click
from agentcli import UsageError, emit, json_option

from recipes import store
from recipes.commands.shared import dir_option, refusing, resolve_dir
from recipes.models import (
    MACRO_KEYS,
    OPTIONAL_NUTRIENT_KEYS,
    PRODUCT_SOURCES,
    Ingredient,
    Macros,
    Recipe,
)
from recipes.render import describe

# Rounding in published tables, and foods that are nearly pure macronutrient,
# can put the sum a little over the weight with nothing actually wrong. The
# absolute term keeps sub-2 g portions quiet, where a tenth of a gram of
# rounding is already worth more than the proportional slack.
_MASS_SLACK = 1.05
_MASS_GRACE_G = 0.5

# Pure fat, around 900 kcal per 100 g, is the densest food there is. Checked
# separately from the macro masses because ethanol carries energy that no
# macronutrient accounts for: a spirit is 0 g of macros and far from 0 kcal.
_MAX_KCAL_PER_100G = 900

# Named once: both warnings end with it, and it is the whole point of them.
# "Drop `grams`" is deliberately absent -- for a 42 g portion of a per-100 g
# source, dropping `grams` keeps the same wrong numbers and silences the
# warning, which is the original bug wearing a different hat.
_RULE = (
    "nutrients must describe the stated grams, so scale a per-100 g source "
    "to the portion; omit `grams` only when the portion really is 100 g"
)


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


def _implausible(item: Ingredient) -> list[str]:
    """Nutrients that cannot describe a portion this small.

    Sources publish per 100 g, so passing their figures beside a real portion
    weight silently multiplies the ingredient. Two independent bounds catch
    it: macronutrients cannot outweigh the food holding them, and nothing is
    denser in energy than pure fat. Neither is exhaustive -- a plausible
    number can still be the wrong one -- so these warn and never refuse.
    """
    if item.macros is None:
        return []

    warnings: list[str] = []
    mass = sum(
        getattr(item.macros, key) or 0 for key in ("protein", "fat", "carbs")
    )
    if mass > item.grams * _MASS_SLACK + _MASS_GRACE_G:
        warnings.append(
            f"{item.name}: {mass:g} g of protein, fat and carbs in a "
            f"{item.grams:g} g portion; {_RULE}"
        )

    density = (item.macros.kcal or 0) / item.grams * 100
    if density > _MAX_KCAL_PER_100G:
        warnings.append(
            f"{item.name}: {density:.0f} kcal per 100 g, denser than pure "
            f"fat; {_RULE}"
        )

    return warnings


def _ingredient(item: dict[str, Any]) -> Ingredient:
    missing = [key for key in MACRO_KEYS if item.get(key) is None]
    if missing:
        raise UsageError(f"input nutrients missing {', '.join(missing)}")

    values: dict[str, float | None] = {}
    for key in (*MACRO_KEYS, *OPTIONAL_NUTRIENT_KEYS):
        value = item.get(key)
        if value is None:
            values[key] = None
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise UsageError(f"{key} must be a number or null")
        if not math.isfinite(value) or value < 0:
            raise UsageError(f"{key} must be non-negative and finite")
        values[key] = float(value)

    grams = item.get("grams") or 100
    if (
        isinstance(grams, bool)
        or not isinstance(grams, (int, float))
        or not math.isfinite(grams)
        or grams <= 0
    ):
        raise UsageError("grams must be a positive finite number")

    source = str(item.get("source") or "manual")
    if source not in PRODUCT_SOURCES:
        source = "manual"
    name = str(item.get("name") or item.get("title") or "Ingredient")
    return Ingredient(
        source=source,
        id=str(item.get("id") or name),
        grams=float(grams),
        name=name,
        macros=Macros(**values),
    )


@click.command("edit")
@click.argument("name")
@click.option(
    "--input",
    "input_file",
    type=click.File("r", encoding="utf-8"),
    help=(
        "Append one JSON item from PATH, or '-' for stdin. Its nutrients "
        "must describe its own 'grams'; sources publish per 100 g, so scale "
        "them to the portion. Omitting 'grams' means a 100 g portion."
    ),
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
    stored = store.find(root, name)
    path = stored.path if stored else store.path_for(root, name)
    if stored is None:
        store.write(path, Recipe(name=name))

    if input_file is not None:
        recipe = store.load_recipe(path)
        ingredient = _ingredient(_input_item(input_file))
        warnings = _implausible(ingredient)
        recipe.ingredients.append(ingredient)
        store.write(path, recipe)

        # Like `resolve`, `--json` carries its diagnostics in the payload: the
        # caller who pipes this is the one who needs them, and stderr is not
        # where they are looking. A human gets them on stderr instead, so
        # stdout stays the one path a shell can consume.
        if not json_output:
            for warning in warnings:
                click.echo(f"warning: {warning}", err=True)

        emit(
            {**describe(recipe), "path": str(path), "warnings": warnings},
            json_output=json_output,
            human=lambda result: [result["path"]],
        )
        return

    click.edit(filename=str(path))
    recipe = store.load_recipe(path)
    emit(
        {"name": recipe.name, "path": str(path)},
        json_output=json_output,
        human=lambda result: [result["path"]],
    )
