"""Command-line entry point. Groups only -- logic lives in `commands/`."""

import click
from agentcli import JsonAwareGroup, skill_group

from recipes import __version__
from recipes.commands.edit import edit
from recipes.commands.resolve import resolve
from recipes.commands.share import share
from recipes.commands.show import show

EPILOG = """\b
Exit codes: 0 success, 1 invalid or incomplete recipe."""


# JsonAwareGroup keeps the `--json` promise for errors click raises early.
@click.group(
    cls=JsonAwareGroup,
    context_settings={"help_option_names": ["-h", "--help"]},
    epilog=EPILOG,
)
@click.version_option(__version__)
def main() -> None:
    """Edit, resolve, view, and share local YAML recipes.

    Recipes are private user data: one YAML file each, under XDG config or a
    `--dir` of your choosing, with git owning their history.

    `ctx.obj` carries the product lookup: tests and embedders inject one, and
    the commands that resolve references build the default reader without it.
    """


for command in (
    skill_group(name="recipes", package="recipes"),
    edit,
    show,
    resolve,
    share,
):
    main.add_command(command)
