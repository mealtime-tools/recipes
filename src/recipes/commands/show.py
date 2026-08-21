"""`recipes show` — one stored recipe, with totals when it has them."""

from collections.abc import Iterable
from pathlib import Path

import click
from agentcli import emit, json_option

from recipes.commands.shared import dir_option, refusing, require_recipe
from recipes.render import describe, recipe_lines


@click.command("show")
@click.argument("name")
@click.option(
    "--servings",
    type=click.IntRange(min=1),
    default=None,
    help="Recompute per-serving macros for this many servings.",
)
@dir_option
@json_option
@refusing
def show(
    name: str,
    servings: int | None,
    directory: Path | None,
    json_output: bool,
) -> None:
    """Print the recipe stored under NAME, and the file it lives in."""
    stored = require_recipe(directory, name)
    recipe = stored.recipe

    # A --servings override is a question, not an edit: nothing is written.
    if servings is not None:
        recipe.servings = servings

    emit(
        describe(recipe) | {"path": str(stored.path)},
        json_output=json_output,
        human=_human,
    )


def _human(payload: dict) -> Iterable[str]:
    yield from recipe_lines(payload)

    # Named because editing the file is how a recipe is changed.
    yield f"# {payload['path']}"
