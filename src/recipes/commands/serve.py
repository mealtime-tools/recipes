"""`recipes serve` — serve plate with the local recipe and product API."""

from pathlib import Path

import click

from recipes.commands.shared import (
    dir_option,
    products_option,
    refusing,
    resolve_dir,
)
from recipes.products import resolve_lookup
from recipes.server import create_server

_LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "::1")


@click.command("serve")
@dir_option
@products_option
@click.option(
    "--port",
    type=int,
    default=8000,
    help="Port to serve on. Default: 8000.",
)
@click.option(
    "--host",
    default="127.0.0.1",
    help="Host to bind to. Default: 127.0.0.1 (loopback).",
)
@click.pass_context
@refusing
def serve(
    ctx: click.Context,
    directory: Path | None,
    products: Path | None,
    port: int,
    host: str,
) -> None:
    """Serve plate and the recipe store over HTTP."""
    recipe_dir = resolve_dir(directory)
    lookup = resolve_lookup(ctx, products)

    # Any host other than loopback exposes user data and product queries.
    if host not in _LOOPBACK_HOSTS:
        click.echo(
            f"Warning: binding to {host}. The server reads and writes recipe "
            "files and reaches the network through products.",
            err=True,
        )

    server = create_server(host, port, recipe_dir, lookup)
    click.echo(
        f"Serving plate at http://{host}:{port}/ (recipes: {recipe_dir})"
    )

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
