"""Refusals, routed through the `--json` contract.

`click.ClickException` prints to stderr, which is right for a human and wrong
for `--json`: a caller promised exactly one JSON object on stdout should not
have to merge two streams to find out what went wrong. The exit codes stay
agentcli's, so they cannot drift from the shared table.
"""

from typing import Any, NoReturn

import click
from agentcli import AssertionFailure, UsageError, dumps, emit_error

REFUSED = UsageError.exit_code
UNMET = AssertionFailure.exit_code


def refuse(
    message: str, *, json_output: bool, exit_code: int = REFUSED
) -> NoReturn:
    """Report a refusal and exit with agentcli's code for it."""
    emit_error(message, json_output=json_output)
    raise SystemExit(exit_code)


def refuse_with(
    message: str,
    detail: dict[str, Any],
    *,
    json_output: bool,
    exit_code: int = REFUSED,
) -> NoReturn:
    """Refuse, carrying structure a caller can act on.

    Still exactly one object on stdout, so naming the missing ingredients
    costs no second stream and no second parse.
    """
    if json_output:
        # agentcli's failure envelope, plus the detail under `data`, so a
        # consumer still branches on `ok` alone and never parses a message.
        click.echo(
            dumps({"ok": False, "error": {"message": message}, "data": detail})
        )
    else:
        click.echo(message, err=True)

    raise SystemExit(exit_code)
