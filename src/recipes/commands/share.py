"""`recipes share` — the self-contained link, and its length.

The length is part of the answer: a QR code is the real size constraint, and
an 11-ingredient recipe with a 200-character note measures 652 characters,
which is a version 18 symbol and comfortably scannable.
"""

from collections.abc import Iterable
from pathlib import Path

import click
from agentcli import emit, json_option

from recipes.codec import share_url
from recipes.commands.shared import dir_option, refusing, require_recipe
from recipes.viewer import viewer_url


@click.command("share")
@click.argument("name")
@dir_option
@json_option
@refusing
def share(name: str, directory: Path | None, json_output: bool) -> None:
    """Print a link that carries the whole of NAME, resolvable by nobody.

    The link points at the deployed Plate page; set $RECIPES_VIEWER_URL to
    point it at your own deployment instead.
    """
    recipe = require_recipe(directory, name).recipe
    url = share_url(recipe, viewer_url())

    emit(
        {"name": recipe.name, "url": url, "length": len(url)},
        json_output=json_output,
        human=_human,
    )


def _human(payload: dict) -> Iterable[str]:
    yield payload["url"]
    yield f"# {payload['length']} characters"
