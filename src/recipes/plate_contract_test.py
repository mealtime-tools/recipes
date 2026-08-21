"""A file exported by the viewer has to load here with no editing.

Plate is a separate, publishable static site and it depends on nothing. This
package depends on it, so the compatibility check belongs on this side: plate
commits one exported document as a contract artifact, and these tests read that
exact file.

The direction matters. When plate's emitter changes, its own suite refuses to
pass until the fixture is refreshed; refreshing it makes these tests read the
new bytes. Neither suite needs the other language's runtime, and neither can
drift without something going red.
"""

import pytest
import yaml
from plate import contract_fixture

from recipes.macros import recipe_macros, unresolved
from recipes.store import recipe_from_mapping


@pytest.fixture
def exported() -> str:
    """The document plate says it hands out."""
    # Not skippable: plate ships this file, so its absence is a broken
    # dependency rather than an environment this test cannot run in.
    return contract_fixture().read_text(encoding="utf-8")


def test_an_exported_file_loads_with_no_editing(exported: str) -> None:
    recipe = recipe_from_mapping(yaml.safe_load(exported))

    assert recipe.name == "Sourdough Pizza"
    assert recipe.servings == 2
    # A block scalar has to survive the round trip, or a method becomes one line.
    assert "\n" in recipe.notes
    assert [item.grams for item in recipe.ingredients] == [475, 100, 75]


def test_an_exported_file_totals_rather_than_refusing(exported: str) -> None:
    """The point of carrying macros in the link: it is complete on arrival."""
    recipe = recipe_from_mapping(yaml.safe_load(exported))

    assert unresolved(recipe) == []

    macros = recipe_macros(recipe)
    # 475g at 268/100 + 100g at 34/100 + 75g at 280/100 = 1517 kcal.
    assert macros.total["kcal"] == pytest.approx(1517.0)
    assert macros.per_serving["kcal"] == pytest.approx(758.5)


def test_an_export_carries_no_invented_product_reference(
    exported: str,
) -> None:
    """A fabricated source and id would be worse than none.

    A share link has no references in it, so any that appeared here would be
    guesses -- and `resolve --force` would later read the wrong product and
    overwrite good macros with it.
    """
    raw = yaml.safe_load(exported)

    for item in raw["ingredients"]:
        assert "source" not in item
        assert "id" not in item


def test_resolve_leaves_an_exported_file_alone(
    exported: str, tmp_path
) -> None:
    """It arrives complete, so the idempotent path must not touch it."""
    from recipes.resolve import resolve_recipe

    recipe = recipe_from_mapping(yaml.safe_load(exported))

    outcome = resolve_recipe(recipe, lookup=None)

    assert outcome.errors == []
    assert outcome.changes == []
