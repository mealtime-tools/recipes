"""`recipes resolve` — freeze a recipe's macros. The only verb that writes.

Recipes are authored by editing YAML: an agent is a better text editor than
any flag set this CLI could offer. The one thing it must never do is
transcribe macro numbers by hand, which is what this command is for. The file
declares intent — a `(source, id)` reference and an amount — and every number
is derived from the product database, once, and frozen.
"""

from collections.abc import Iterable
from pathlib import Path

import click
from agentcli import emit, json_option

from recipes.commands.shared import (
    dir_option,
    products_option,
    refusing,
    require_recipe,
)
from recipes.errors import refuse, refuse_with
from recipes.products import resolve_lookup
from recipes.render import describe, recipe_lines
from recipes.resolve import resolve_and_write


@click.command("resolve")
@click.argument("name")
@click.option(
    "--force",
    is_flag=True,
    help="Re-read references that already carry macros, and report changes.",
)
@dir_option
@products_option
@json_option
@click.pass_context
@refusing
def resolve(
    ctx: click.Context,
    name: str,
    force: bool,
    directory: Path | None,
    products: Path | None,
    json_output: bool,
) -> None:
    """Resolve the references of the recipe stored under NAME and write it.

    Idempotent: an ingredient that already carries macros is left alone, so a
    second run changes nothing. `--force` re-reads every reference instead.
    """
    stored = require_recipe(directory, name)
    outcome, written = resolve_and_write(
        stored.path,
        stored.recipe,
        resolve_lookup(ctx, products),
        force=force,
    )

    if not outcome.recipe.ingredients:
        refuse(f"{name}: has no ingredients", json_output=json_output)

    # Rule 12: nothing is written for a recipe that still cannot be totalled.
    if outcome.errors:
        refuse_with(
            f"{stored.recipe.name}: "
            f"{len(outcome.errors)} ingredients unresolved",
            {"errors": outcome.errors},
            json_output=json_output,
        )

    emit(
        describe(outcome.recipe)
        | {
            "path": str(stored.path),
            "written": written,
            "resolved": outcome.resolved,
            "changes": outcome.changes,
            "warnings": outcome.warnings,
        },
        json_output=json_output,
        human=_human,
    )


def _human(payload: dict) -> Iterable[str]:
    yield from recipe_lines(payload)

    for reference in payload["resolved"]:
        yield f"  resolved: {reference}"

    for change in payload["changes"]:
        for field, values in change["fields"].items():
            before, after = values["before"], values["after"]
            yield f"  changed: {change['name']} {field} {before} -> {after}"

    # Said out loud: data the database could not confirm is stale, not wrong.
    for warning in payload["warnings"]:
        yield f"  kept last good snapshot: {warning}"

    yield f"# {payload['path']}{'' if payload['written'] else ' (unchanged)'}"
