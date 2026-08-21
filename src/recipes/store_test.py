"""The YAML store: one file per recipe, identified by the name inside it."""

import pytest

from recipes import store
from recipes.models import Ingredient, Macros, Recipe

MINIMAL = """\
name: Chicken Bowl
servings: 2
ingredients:
  - source: coles
    id: '1047'
    grams: 200
"""


def pizza() -> Recipe:
    return Recipe(
        name="Sourdough Pizza",
        servings=2,
        tags=["dinner"],
        notes="Stretch cold, from the edges.\nBake 8 min at max heat.",
        ingredients=[
            Ingredient(
                source="coles",
                id="0042",
                grams=475,
                name="Pizza Dough",
                macros=Macros(kcal=268.0, protein=8.9, fat=3.1, carbs=49.2),
            ),
            Ingredient(source="manual", id="Passata", grams=100),
        ],
    )


def test_yaml_round_trips_every_field(tmp_path) -> None:
    path = tmp_path / "pizza.yaml"
    store.write(path, pizza())
    text = path.read_text()

    # A literal block, because notes are method text a human reads and diffs.
    assert "notes: |-" in text
    # Quoted, because a leading-zero id is not the integer 42.
    assert "id: '0042'" in text
    assert store.load_recipe(path) == pizza()


def test_an_unresolved_ingredient_stays_unresolved(tmp_path) -> None:
    """No macros key rather than zeros, so a reader can tell the difference."""
    path = tmp_path / "pizza.yaml"
    store.write(path, pizza())

    assert "macros" not in path.read_text().split("- source: manual")[1]
    assert store.load_recipe(path).ingredients[1].macros is None


def test_a_hand_written_ingredient_needs_only_a_reference(tmp_path) -> None:
    """What an agent writes: intent, with no macro number by hand."""
    path = tmp_path / "bowl.yaml"
    path.write_text(MINIMAL)

    recipe = store.load_recipe(path)
    item = recipe.ingredients[0]

    assert (recipe.name, recipe.servings) == ("Chicken Bowl", 2)
    assert (item.source, item.id, item.grams) == ("coles", "1047", 200.0)
    assert (item.name, item.macros) == (None, None)


def test_an_unknown_source_is_refused_at_ingress(tmp_path) -> None:
    """Refused now, rather than looking like a database outage forever."""
    path = tmp_path / "bowl.yaml"
    path.write_text(MINIMAL.replace("coles", "local"))

    with pytest.raises(store.StoreError, match="unknown source"):
        store.load_recipe(path)


def test_the_name_field_is_what_a_lookup_matches(tmp_path) -> None:
    """Editing `name:` by hand must not make a recipe unfindable."""
    path = tmp_path / "whatever.yaml"
    store.write(path, pizza())
    path.write_text(path.read_text().replace("Sourdough Pizza", "Focaccia"))

    assert store.find(tmp_path, "Sourdough Pizza") is None
    assert store.find(tmp_path, "  focaccia ").path == path


def test_two_files_claiming_one_name_are_both_reported(tmp_path) -> None:
    """Answering with whichever file was listed first is not an answer."""
    store.write(tmp_path / "one.yaml", pizza())
    store.write(tmp_path / "two.yaml", pizza())

    with pytest.raises(store.StoreError) as caught:
        store.find(tmp_path, "Sourdough Pizza")

    assert "one.yaml" in str(caught.value)
    assert "two.yaml" in str(caught.value)

    # A search over the directory is ambiguous for the same reason.
    with pytest.raises(store.StoreError):
        store.load_all(tmp_path)


def test_identical_bytes_are_not_rewritten(tmp_path) -> None:
    """Touching a git-tracked file for nothing costs a human a diff."""
    path = tmp_path / "pizza.yaml"

    assert store.write(path, pizza()) is True
    assert store.write(path, pizza()) is False


def test_case_and_whitespace_are_the_same_recipe() -> None:
    assert store.recipe_key("Chicken  Bowl") == store.recipe_key(
        " chicken bowl "
    )


def test_suggested_names_that_slug_alike_stay_distinct() -> None:
    """Cosmetic, but two recipes must not be offered one filename."""
    slugged = {
        store.filename_for(name)
        for name in ("Chicken Bowl", "Chicken/Bowl", "Chicken-Bowl")
    }

    assert len(slugged) == 3


def test_a_suggested_name_cannot_escape_the_directory(tmp_path) -> None:
    path = store.path_for(tmp_path, "../../etc/passwd")

    assert path.parent == tmp_path
    assert path.suffix == store.SUFFIX


def test_an_unnamed_recipe_is_refused() -> None:
    with pytest.raises(store.StoreError):
        store.filename_for("   ")
