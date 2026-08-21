"""Command-line entry point. Groups only -- logic lives in `commands/`."""

import click
from agentcli import JsonAwareGroup, guide_command, skill_group

from recipes import __version__
from recipes.commands.fit import fit
from recipes.commands.resolve import resolve
from recipes.commands.search import search
from recipes.commands.serve import serve
from recipes.commands.share import share
from recipes.commands.show import show
from recipes.guide import GUIDE

EPILOG = """\b
Run `recipes guide` for the full manual: where recipes are stored, the share
URL format, and why an unresolved ingredient refuses to total.

\b
Exit codes: 0 success, 1 usage error or refused input, 2 remote error, 3 a
stated constraint did not hold (`fit` found no factor). 4 is unused here."""


# JsonAwareGroup keeps the `--json` promise for failures click raises before
# a subcommand has parsed anything, such as a mistyped flag.
@click.group(
    cls=JsonAwareGroup,
    context_settings={"help_option_names": ["-h", "--help"]},
    epilog=EPILOG,
)
@click.version_option(__version__)
def main() -> None:
    """A searchable store of your own recipes, and the arithmetic.

    Recipes are private user data: one YAML file each, under XDG config or a
    `--dir` of your choosing, with git owning their history. They are authored
    by editing that YAML; `resolve` is the only command that writes.

    `ctx.obj` carries the product lookup: tests and embedders inject one, and
    the commands that resolve references build the default reader without it.
    """


for command in (
    guide_command(GUIDE),
    skill_group(name="recipes", package="recipes"),
    search,
    show,
    resolve,
    fit,
    share,
    serve,
):
    main.add_command(command)
