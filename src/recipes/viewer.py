"""Where a share link points. Configuration, with the deployment as default.

A link is the durable artefact, so it must point at a page that will still
render it later. Plate is deployed publicly at the address below, and that is
the page this codec was written against, so it is the default. Set
`$RECIPES_VIEWER_URL` to point links at your own deployment instead.
"""

import os
from collections.abc import Mapping

from dotenv import load_dotenv

ENV_VAR = "RECIPES_VIEWER_URL"

DEFAULT_VIEWER_URL = "https://mealtime-tools.github.io/plate/"


def viewer_url(env: Mapping[str, str] | None = None) -> str:
    """The configured viewer base URL, or the deployed Plate page."""
    # `.env` fills gaps in the environment rather than overriding it.
    if env is None:
        load_dotenv()
        env = os.environ

    return (env.get(ENV_VAR) or "").strip() or DEFAULT_VIEWER_URL
