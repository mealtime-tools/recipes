"""Recipe arithmetic and the single proportional fit."""

from recipes.macros import fit_recipe, recipe_macros
from recipes.models import Ingredient, Macros, Recipe


def chicken(grams: float = 200, servings: int = 2) -> Recipe:
    """Per 100 g: 165 kcal, 31 g protein. Two servings."""
    return Recipe(
        name="Chicken",
        servings=servings,
        ingredients=[
            Ingredient(
                source="coles",
                id="1",
                grams=grams,
                name="Chicken breast",
                macros=Macros(kcal=165.0, protein=31.0, fat=3.6, carbs=0.0),
            )
        ],
    )


def test_totals_scale_by_grams_and_servings() -> None:
    macros = recipe_macros(chicken())

    assert macros.total == {
        "kcal": 330.0,
        "protein": 62.0,
        "fat": 7.2,
        "carbs": 0.0,
    }
    assert macros.per_serving["kcal"] == 165.0
    assert macros.per_serving["protein"] == 31.0


def test_fit_scales_up_to_the_protein_floor() -> None:
    outcome = fit_recipe(chicken(), max_kcal=700, min_protein=40)

    assert outcome.fits
    assert outcome.scale == 1.2903
    assert outcome.recipe.ingredients[0].grams == 258.06
    # The scaled recipe is what meets the constraint, to rounding.
    assert recipe_macros(outcome.recipe).per_serving["protein"] == 40.0


def test_fit_leaves_a_fitting_recipe_alone() -> None:
    outcome = fit_recipe(chicken(), max_kcal=700, min_protein=25)

    assert (outcome.fits, outcome.scale) == (True, 1.0)
    assert outcome.recipe.ingredients[0].grams == 200


def test_fit_reports_the_gap_and_the_excess_at_the_floor() -> None:
    """Protein floor and calorie ceiling cross: 25 g protein per 500 kcal."""
    recipe = Recipe(
        name="Pasta",
        servings=1,
        ingredients=[
            Ingredient(
                source="coles",
                id="2",
                grams=100,
                name="Pasta bake",
                macros=Macros(kcal=500.0, protein=25.0, fat=20.0, carbs=60.0),
            )
        ],
    )

    outcome = fit_recipe(recipe, max_kcal=700, min_protein=40)

    assert not outcome.fits
    assert outcome.gap == {"protein_g": 15.0, "kcal": 0.0}
    assert outcome.message == "need +15g protein"
    assert outcome.calorie_excess_at_min_protein == 100.0
