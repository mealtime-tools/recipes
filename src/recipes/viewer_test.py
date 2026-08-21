"""Where a share link points: configuration, with a deployed default."""

import pytest

from recipes.viewer import DEFAULT_VIEWER_URL, ENV_VAR, viewer_url


def test_the_configured_base_is_returned() -> None:
    assert viewer_url({ENV_VAR: " https://recipes.example/ "}) == (
        "https://recipes.example/"
    )


@pytest.mark.parametrize("env", [{}, {ENV_VAR: "   "}], ids=["unset", "blank"])
def test_an_unconfigured_viewer_falls_back_to_the_deployment(
    env: dict,
) -> None:
    """Plate is deployed and public, so a link without configuration works."""
    assert viewer_url(env) == DEFAULT_VIEWER_URL


def test_the_default_is_the_deployed_plate_page() -> None:
    """The fallback must be the page that can actually render the payload."""
    assert DEFAULT_VIEWER_URL == "https://mealtime-tools.github.io/plate/"
