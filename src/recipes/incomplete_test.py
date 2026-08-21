"""Rule 12: an unresolvable ingredient is named and never silently totalled.

This is the bug the redesign exists for. The TypeScript web path turned a
lookup miss into an ingredient with no macros and then totalled the recipe as
if it were whole, reporting a confident number that omitted 300 g of a 450 g
recipe. Every assertion here is about refusing rather than answering.
"""

import pytest

from recipes import macros
from recipes.models import Ingredient, Macros, Recipe


def partial_recipe() -> Recipe:
    """One resolved ingredient and two that no source can answer."""
    return Recipe(
        name="Bowl",
        servings=1,
        ingredients=[
            Ingredient(
                source="coles",
                id="1",
                grams=150,
                name="Chicken",
                macros=Macros(kcal=165.0, protein=31.0, fat=3.6, carbs=0.0),
            ),
            Ingredient(source="coles", id="404", grams=200),
            Ingredient(source="usda", id="405", grams=100),
        ],
    )


def test_unresolved_ingredients_are_named() -> None:
    recipe = partial_recipe()

    assert not macros.is_complete(recipe)
    assert macros.unresolved(recipe) == [
        "coles:404: no macro snapshot",
        "usda:405: no macro snapshot",
    ]


def test_totals_refuse_an_incomplete_recipe() -> None:
    with pytest.raises(macros.IncompleteRecipe):
        macros.recipe_macros(partial_recipe())


def test_fit_refuses_an_incomplete_recipe() -> None:
    with pytest.raises(macros.IncompleteRecipe):
        macros.fit_recipe(partial_recipe(), max_kcal=700, min_protein=40)
