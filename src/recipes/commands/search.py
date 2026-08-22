"""`recipes search` — stored recipes as ranked, comparable candidates.

Recipes is primarily a data source. "What can I cook under 400 kcal a serving
with 30 g of protein" is the same question eatout answers about restaurants, so
this emits agentcli's shared candidate record, accepts the shared filters and
uses the shared ranking. An orchestrator merges both streams without knowing
which tool produced which record.
"""

from collections.abc import Iterable
from pathlib import Path
from typing import Any

import click
from agentcli import (
    candidate,
    emit,
    json_option,
    limit_option,
    macro_options,
    matches,
    rank,
    unverifiable,
)

from recipes import store
from recipes.commands.shared import dir_option, refusing, resolve_dir
from recipes.macros import (
    is_complete,
    parse_servings,
    recipe_macros,
    unresolved,
)
from recipes.render import ingredient_rows, macro_summary


@click.command("search")
@macro_options
@dir_option
@limit_option(default=0)
@json_option
@refusing
def search(
    max_kcal: float | None,
    min_protein: float | None,
    directory: Path | None,
    limit: int,
    json_output: bool,
) -> None:
    """Stored recipes that provably match, ranked by protein per 100 kcal.

    Matching nothing is a success with an empty list. `--limit 0` means no
    limit.
    """
    records = [
        _candidate_of(stored)
        for stored in store.load_all(resolve_dir(directory))
    ]
    filters = {"max_kcal": max_kcal, "min_protein": min_protein}

    # Named rather than dropped: "nothing matched" and "two I could not check"
    # are different answers, and only one of them is about the filters.
    checkable = [r for r in records if _checkable(r, filters)]
    skipped = [_skipped_of(r) for r in records if not _checkable(r, filters)]

    passing = rank([r for r in checkable if matches(r, **filters)])
    found = passing[:limit] if limit else passing

    emit(
        {
            "count": len(found),
            "candidates": found,
            "skipped_incomplete": skipped,
        },
        json_output=json_output,
        human=_human,
    )


def _candidate_of(stored: store.Stored) -> dict[str, Any]:
    """One stored recipe as the shared candidate record.

    Macros come from the single totalling implementation or not at all, so an
    incomplete recipe publishes no macro rather than an understated one. The
    id is the recipe's identity key, which `show`, `fit`, `share` and
    `resolve` all accept as a name.

    `per_serving` appears twice on purpose: the shared record's copy is what
    an orchestrator ranks and filters on, and agentcli fixes its keys at the
    four macros; `detail.per_serving` is this recipe's own answer, fibre
    included.
    """
    recipe = stored.recipe
    totals = recipe_macros(recipe) if is_complete(recipe) else None

    return candidate(
        kind="recipe",
        identifier=store.recipe_key(recipe.name),
        name=recipe.name,
        per_serving=dict(totals.per_serving) if totals else {},
        detail={
            "servings": parse_servings(recipe.servings),
            "tags": list(recipe.tags),
            "notes": recipe.notes,
            "ingredients": ingredient_rows(recipe),
            "total": totals.total if totals else None,
            # The shared record above is agentcli's, and it carries the four
            # macros it defines and no more, so every nutrient this recipe can
            # report is published here as well. Without it a caller wanting
            # fibre per serving would divide a total by `servings` itself,
            # which is the hand-arithmetic this tool exists to own.
            "per_serving": dict(totals.per_serving) if totals else None,
            # A nutrient no total could report, and the ingredients that are
            # the reason: absent from `detail.per_serving` is the fact, and
            # this is why.
            "unresolved": unresolved(recipe),
            # The file to edit: authoring a recipe is editing its YAML.
            "path": str(stored.path),
        },
    )


def _checkable(record: dict[str, Any], filters: dict[str, Any]) -> bool:
    """Whether this recipe's macros can answer the question being asked.

    Rule 12 first: a recipe with an unresolved ingredient publishes no macros,
    so it can never be shown to pass. `unverifiable` is the shared spelling of
    the same refusal for a source whose macros are individually optional, and
    applying both is what stops this path becoming a second, laxer notion of
    completeness.
    """
    return record["complete"] and not unverifiable(record, **filters)


def _skipped_of(record: dict[str, Any]) -> dict[str, Any]:
    """A recipe that could not be judged, named by what is missing from it."""
    return {
        "name": record["name"],
        "unresolved": record["detail"]["unresolved"],
    }


def _human(payload: dict[str, Any]) -> Iterable[str]:
    # Said out loud, because a silent success and an empty directory look
    # identical to a person and only one of them is what they meant.
    if not payload["candidates"]:
        yield "# no candidates"

    for record in payload["candidates"]:
        servings = record["detail"]["servings"]
        plural = "" if servings == 1 else "s"
        yield f"{record['name']}  ({servings} serving{plural})"
        # This recipe's own figures, not the shared record's four: a person
        # reading the ranked list would otherwise conclude a recipe has no
        # fibre where `show` prints it, and go and divide a total by hand.
        yield (
            f"  per serving  {macro_summary(record['detail']['per_serving'])}"
        )

    for item in payload["skipped_incomplete"]:
        missing = "; ".join(item["unresolved"])
        yield f"# skipped, incomplete: {item['name']}: {missing}"
