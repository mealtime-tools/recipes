"""What every command that touches stored recipes needs.

The refusal decorator is the reason this module exists: the domain raises
`StoreError`, `ShareUrlError` and `IncompleteRecipe`, and every command turns
those into the same thing -- one JSON object and an exit code. Doing that once
keeps the command bodies straight-line code and stops the mapping drifting.
"""

import functools
from collections.abc import Callable
from pathlib import Path
from typing import Any

import click

from recipes import store
from recipes.codec import ShareUrlError
from recipes.errors import refuse, refuse_with
from recipes.macros import IncompleteRecipe
from recipes.store import Stored, StoreError, default_dir

DIRECTORY = click.Path(file_okay=False, path_type=Path)


def dir_option(f: Callable[..., Any]) -> Callable[..., Any]:
    """Where recipes live. A user may point this at a private git repo."""
    return click.option(
        "--dir",
        "directory",
        type=DIRECTORY,
        default=None,
        help=f"Recipe directory. Default: {default_dir()}",
    )(f)


def products_option(f: Callable[..., Any]) -> Callable[..., Any]:
    """Where product records are read from, for the commands that resolve."""
    return click.option(
        "--products",
        type=DIRECTORY,
        default=None,
        help="Directory of pantry-format JSONL product files.",
    )(f)


def refusing(f: Callable[..., Any]) -> Callable[..., Any]:
    """Map the domain's refusals onto the exit-code and `--json` contract.

    Applied innermost, below the click decorators, so it sees the parsed
    `json_output` flag and the command body needs no error handling at all.
    """

    @functools.wraps(f)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        json_output = bool(kwargs.get("json_output"))
        try:
            return f(*args, **kwargs)
        except (StoreError, ShareUrlError) as exc:
            refuse(str(exc), json_output=json_output)
        except IncompleteRecipe as exc:
            # Named per ingredient, which is the whole point of refusing.
            refuse_with(
                str(exc), {"errors": exc.errors}, json_output=json_output
            )

    return wrapper


def resolve_dir(directory: Path | None) -> Path:
    return directory or default_dir()


def require_recipe(directory: Path | None, name: str) -> Stored:
    """The stored recipe and its file, or a refusal. Never None to forget."""
    return store.require(resolve_dir(directory), name)
