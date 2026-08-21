"""`recipes fit` — the single proportional scaling solution, or the gap.

One factor for the whole recipe. It never substitutes an ingredient, so a
refusal is a real constraint conflict and is reported as the shortfall in
grams of protein and kcal, plus how far over the ceiling the recipe would be
at exactly the protein floor.
"""

from collections.abc import Iterable
from pathlib import Path

import click
from agentcli import emit, json_option

from recipes.commands.shared import dir_option, refusing, require_recipe
from recipes.errors import UNMET, refuse_with
from recipes.macros import fit_recipe
from recipes.render import describe, recipe_lines


@click.command("fit")
@click.argument("name")
@click.option(
    "--max-kcal",
    type=click.FloatRange(min=0, min_open=True),
    required=True,
    help="Calorie ceiling per serving.",
)
@click.option(
    "--min-protein",
    type=click.FloatRange(min=0, min_open=True),
    required=True,
    help="Protein floor per serving, in grams.",
)
@dir_option
@json_option
@refusing
def fit(
    name: str,
    max_kcal: float,
    min_protein: float,
    directory: Path | None,
    json_output: bool,
) -> None:
    """Scale NAME so one serving meets both constraints."""
    recipe = require_recipe(directory, name).recipe
    outcome = fit_recipe(recipe, max_kcal=max_kcal, min_protein=min_protein)

    # A stated constraint that does not hold is exit 3, not a usage error:
    # the request was valid and the answer is that no factor satisfies it.
    if not outcome.fits:
        detail: dict = {"fits": False, "gap": outcome.gap}
        if outcome.calorie_excess_at_min_protein is not None:
            detail["calorie_excess_at_min_protein"] = (
                outcome.calorie_excess_at_min_protein
            )
        refuse_with(
            outcome.message, detail, json_output=json_output, exit_code=UNMET
        )

    emit(
        {
            "fits": True,
            "scale": outcome.scale,
            "recipe": describe(outcome.recipe),
        },
        json_output=json_output,
        human=_human,
    )


def _human(payload: dict) -> Iterable[str]:
    yield f"fits at scale {payload['scale']:g}"
    yield from recipe_lines(payload["recipe"])
