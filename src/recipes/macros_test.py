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


def soup(servings: int = 2) -> Recipe:
    """Both ingredients carry fibre; only the soy milk carries sugar."""
    return Recipe(
        name="Soup",
        servings=servings,
        ingredients=[
            Ingredient(
                source="coles",
                id="4499631",
                grams=250,
                name="Soy milk",
                macros=Macros(
                    kcal=42.0,
                    protein=3.0,
                    fat=1.6,
                    carbs=3.3,
                    fiber=0.2,
                    sugar=1.0,
                ),
            ),
            Ingredient(
                source="afcd",
                id="F004193",
                grams=10,
                name="Garlic, raw",
                macros=Macros(
                    kcal=139.0, protein=6.4, fat=0.5, carbs=23.0, fiber=17.0
                ),
            ),
        ],
    )


def test_a_nutrient_every_ingredient_carries_is_totalled() -> None:
    macros = recipe_macros(soup())

    # 250 g at 0.2/100 g plus 10 g at 17/100 g is 2.2 g of fibre.
    assert macros.total["fiber"] == 2.2
    assert macros.per_serving["fiber"] == 1.1
    assert "fiber" not in macros.missing


def test_a_nutrient_one_ingredient_lacks_is_omitted_and_named() -> None:
    """A partial fibre total under-reports, so there is no partial total."""
    macros = recipe_macros(soup())

    assert "sugar" not in macros.total
    assert "sugar" not in macros.per_serving
    assert macros.missing == {"sugar": ["afcd:F004193: no sugar"]}


def test_the_four_macros_are_reported_whatever_else_is_missing() -> None:
    """Widening the snapshot must not narrow what a recipe already totals."""
    macros = recipe_macros(chicken())

    assert set(macros.total) == {"kcal", "protein", "fat", "carbs"}
    assert macros.missing == {
        "fiber": ["coles:1: no fiber"],
        "sugar": ["coles:1: no sugar"],
    }
