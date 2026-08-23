"""Where a share link points. Configuration, with the deployment as default.

A link is the durable artefact, so it must point at a page that will still
render it later. Plate is deployed publicly at the address below, and that is
the page this codec was written against, so it is the default. Export
`$RECIPES_VIEWER_URL` to point links at your own deployment instead; it is
read from the process environment only, never from a `.env` file.
"""

import os
from collections.abc import Mapping

ENV_VAR = "RECIPES_VIEWER_URL"

DEFAULT_VIEWER_URL = "https://mealtime-tools.github.io/plate/"


def viewer_url(env: Mapping[str, str] | None = None) -> str:
    """The configured viewer base URL, or the deployed Plate page."""
    # Only what the caller exported. `.env` discovery anchors its upward walk
    # at this file's own directory, so an installed copy reached `$HOME/.env`
    # and one stale line there silently redirected every link, from any working
    # directory. A link outlives the process that made it, so it does not get
    # its target from an ambient file. (Discovery falls back to the working
    # directory for REPL and `-c` callers, which has the same problem.)
    if env is None:
        env = os.environ

    return (env.get(ENV_VAR) or "").strip() or DEFAULT_VIEWER_URL
