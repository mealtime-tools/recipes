"""The commands, end to end, against a temporary recipe directory."""

from pathlib import Path

from recipes import store
from recipes.cli import main
from recipes.codec import decode_payload, recipe_from_payload
from recipes.macros import recipe_macros
from recipes.viewer import DEFAULT_VIEWER_URL
from recipes.conftest import FakeLookup, data_of, failure_of, invoke

PIZZA = FakeLookup(
    {
        ("coles", "1"): ("Pizza Dough", 268.0, 8.9, 3.1, 49.2),
        ("coles", "2"): ("Passata", 34.0, 1.6, 0.2, 6.4),
        ("coles", "3"): ("Mozzarella", 280.0, 22.0, 21.0, 1.5),
        ("coles", "4"): ("Chicken Breast", 165.0, 31.0, 3.6, 0.0),
    }
)
NOTES = "Stretch cold, from the edges.\nBake 8 min at max heat."

# What an agent writes: a reference, an amount, and no macro numbers.
PIZZA_YAML = f"""\
name: Sourdough Pizza
servings: 2
tags:
  - dinner
notes: |-
  {NOTES.splitlines()[0]}
  {NOTES.splitlines()[1]}
ingredients:
  - source: coles
    id: '1'
    grams: 475
  - source: coles
    id: '2'
    grams: 100
  - source: coles
    id: '3'
    grams: 75
"""

CHICKEN_YAML = """\
name: Grilled Chicken
ingredients:
  - source: coles
    id: '4'
    grams: 200
"""

VIEWER = "https://recipes.example/"


def author(directory: Path, filename: str, text: str) -> Path:
    """Write a recipe by hand, the way an agent does."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / filename
    path.write_text(text, encoding="utf-8")
    return path


def resolve_recipe(directory: Path, name: str, *args, lookup=PIZZA) -> dict:
    result = invoke(
        main,
        ["resolve", name, "--dir", str(directory), "--json", *args],
        lookup=lookup,
    )
    assert result.exit_code == 0, result.output
    return data_of(result)


def pizza(directory: Path) -> dict:
    author(directory, "pizza.yaml", PIZZA_YAML)
    return resolve_recipe(directory, "Sourdough Pizza")


def test_a_hand_written_recipe_resolves_to_complete(tmp_path) -> None:
    """The agent declares intent; every number comes from the database."""
    resolved = pizza(tmp_path)

    assert resolved["complete"] is True
    assert resolved["written"] is True
    assert resolved["unresolved"] == []
    # Filling in a blank ingredient is the normal course, not a `change`.
    assert resolved["resolved"] == [
        "coles:1: Pizza Dough",
        "coles:2: Passata",
        "coles:3: Mozzarella",
    ]
    assert resolved["changes"] == []
    assert resolved["macros"]["per_serving"]["kcal"] == 758.5
    assert [item["name"] for item in resolved["ingredients"]] == [
        "Pizza Dough",
        "Passata",
        "Mozzarella",
    ]
    assert resolved["path"] == str(tmp_path / "pizza.yaml")


def test_resolve_is_idempotent(tmp_path) -> None:
    """A second run must change nothing, down to the bytes."""
    pizza(tmp_path)
    path = tmp_path / "pizza.yaml"
    before = path.read_text()

    # No lookup at all: an already-resolved recipe needs no product database.
    again = resolve_recipe(tmp_path, "Sourdough Pizza", lookup=FakeLookup({}))

    assert again["written"] is False
    assert (again["resolved"], again["changes"]) == ([], [])
    assert path.read_text() == before


def test_force_re_reads_and_reports_changed_fields(tmp_path) -> None:
    pizza(tmp_path)
    path = tmp_path / "pizza.yaml"
    cheaper = FakeLookup(dict(PIZZA.rows))
    cheaper.rows[("coles", "2")] = ("Passata", 30.0, 1.6, 0.2, 6.4)

    changed = resolve_recipe(
        tmp_path, "Sourdough Pizza", "--force", lookup=cheaper
    )

    assert changed["changes"] == [
        {
            "ref": "coles:2",
            "name": "Passata",
            "fields": {"kcal": {"before": 34.0, "after": 30.0}},
        }
    ]
    assert changed["written"] is True
    assert "kcal: 30.0" in path.read_text()


def test_force_keeps_a_snapshot_the_database_cannot_confirm(tmp_path) -> None:
    """Losing good data to an unavailable source would kill the recipe."""
    resolved = pizza(tmp_path)
    partial = FakeLookup(
        {key: row for key, row in PIZZA.rows.items() if key != ("coles", "3")}
    )

    kept = resolve_recipe(
        tmp_path, "Sourdough Pizza", "--force", lookup=partial
    )

    assert kept["warnings"] == ["coles:3: product not found"]
    assert kept["complete"] is True
    assert kept["macros"] == resolved["macros"]


def test_resolve_refuses_and_writes_nothing_when_a_reference_misses(
    tmp_path,
) -> None:
    """Rule 12: 450 g of ingredients, 250 g unresolvable, file untouched."""
    path = author(
        tmp_path,
        "bowl.yaml",
        """\
name: Bowl
ingredients:
  - source: coles
    id: '4'
    grams: 150
  - source: coles
    id: '404'
    grams: 200
  - source: usda
    id: '405'
    grams: 100
""",
    )
    before = path.read_text()

    result = invoke(
        main,
        ["resolve", "Bowl", "--dir", str(tmp_path), "--json"],
        lookup=PIZZA,
    )
    payload = failure_of(result)

    assert result.exit_code == 1
    assert payload["data"]["errors"] == [
        "coles:404: product not found",
        "usda:405: product not found",
    ]
    assert "total" not in payload["error"]["message"]
    assert path.read_text() == before


def test_a_renamed_recipe_stays_findable(tmp_path) -> None:
    """`name:` is the identity, so an in-place rename is a supported edit."""
    path = author(tmp_path, "pizza.yaml", PIZZA_YAML)
    pizza_data = resolve_recipe(tmp_path, "Sourdough Pizza")
    path.write_text(
        path.read_text().replace("name: Sourdough Pizza", "name: Focaccia")
    )

    shown = data_of(
        invoke(main, ["show", "focaccia", "--dir", str(tmp_path), "--json"])
    )

    assert shown["name"] == "Focaccia"
    assert shown["macros"] == pizza_data["macros"]
    # The filename is cosmetic and is not rewritten to match.
    assert shown["path"] == str(path)


def test_two_files_claiming_one_name_are_refused(tmp_path) -> None:
    author(tmp_path, "one.yaml", PIZZA_YAML)
    author(tmp_path, "two.yaml", PIZZA_YAML)

    result = invoke(
        main, ["show", "Sourdough Pizza", "--dir", str(tmp_path), "--json"]
    )
    message = failure_of(result)["error"]["message"]

    assert result.exit_code == 1
    assert "one.yaml" in message and "two.yaml" in message


def test_share_round_trips_a_whole_recipe(tmp_path, monkeypatch) -> None:
    """The share URL is the durable artefact: it must survive a round trip."""
    monkeypatch.setenv("RECIPES_VIEWER_URL", VIEWER)
    resolved = pizza(tmp_path)

    shared = data_of(
        invoke(
            main,
            ["share", "Sourdough Pizza", "--dir", str(tmp_path), "--json"],
        )
    )
    restored = recipe_from_payload(
        decode_payload(shared["url"].split("#r=")[1])
    )

    assert shared["url"].startswith(f"{VIEWER}#r=")
    assert shared["length"] == len(shared["url"])
    assert (restored.name, restored.servings, restored.notes) == (
        "Sourdough Pizza",
        2,
        NOTES,
    )
    per_serving = resolved["macros"]["per_serving"]
    assert recipe_macros(restored).per_serving == per_serving


def test_share_falls_back_to_the_deployed_viewer(
    tmp_path, monkeypatch
) -> None:
    """With nothing configured, links point at the deployed Plate page."""
    monkeypatch.delenv("RECIPES_VIEWER_URL", raising=False)
    pizza(tmp_path)

    shared = data_of(
        invoke(
            main,
            ["share", "Sourdough Pizza", "--dir", str(tmp_path), "--json"],
        )
    )

    assert shared["url"].startswith(f"{DEFAULT_VIEWER_URL}#r=")


def test_a_configured_viewer_overrides_the_default(
    tmp_path, monkeypatch
) -> None:
    """Someone else's deployment must still win over ours."""
    monkeypatch.setenv("RECIPES_VIEWER_URL", VIEWER)
    pizza(tmp_path)

    shared = data_of(
        invoke(
            main,
            ["share", "Sourdough Pizza", "--dir", str(tmp_path), "--json"],
        )
    )

    assert shared["url"].startswith(f"{VIEWER}#r=")


def test_nothing_is_written_outside_the_given_dir(
    tmp_path, monkeypatch
) -> None:
    """Rule 9: user data goes where it was told, and nowhere else."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    target = tmp_path / "recipes"

    pizza(target)

    assert [path.name for path in target.iterdir()] == ["pizza.yaml"]
    assert not (tmp_path / "xdg").exists()
    assert not (tmp_path / "home").exists()


def test_search_emits_the_shared_candidate_record(tmp_path) -> None:
    """The record an orchestrator merges with eatout's, ranked the same way."""
    pizza(tmp_path)
    author(tmp_path, "chicken.yaml", CHICKEN_YAML)
    resolve_recipe(tmp_path, "Grilled Chicken")

    found = data_of(
        invoke(
            main,
            ["search", "--max-kcal", "900", "--dir", str(tmp_path), "--json"],
        )
    )
    record = found["candidates"][0]

    assert found["count"] == 2
    # Protein per 100 kcal, descending: chicken is denser than pizza.
    assert [item["name"] for item in found["candidates"]] == [
        "Grilled Chicken",
        "Sourdough Pizza",
    ]
    assert record["kind"] == "recipe"
    assert record["id"] == "grilled chicken"
    assert record["complete"] is True
    assert record["per_serving"] == {
        "kcal": 330.0,
        "protein": 62.0,
        "fat": 7.2,
        "carbs": 0.0,
    }
    assert record["detail"]["servings"] == 1
    assert record["detail"]["path"] == str(tmp_path / "chicken.yaml")
    assert found["skipped_incomplete"] == []


def test_search_filters_on_both_macros(tmp_path) -> None:
    """Per serving: pizza is 758.5 kcal and 30.19 g of protein."""
    pizza(tmp_path)

    hit = data_of(
        invoke(
            main,
            [
                "search",
                "--max-kcal",
                "800",
                "--min-protein",
                "30",
                "--dir",
                str(tmp_path),
                "--json",
            ],
        )
    )
    miss = data_of(
        invoke(
            main,
            [
                "search",
                "--max-kcal",
                "800",
                "--min-protein",
                "40",
                "--dir",
                str(tmp_path),
                "--json",
            ],
        )
    )

    assert [item["name"] for item in hit["candidates"]] == ["Sourdough Pizza"]
    # Finding nothing is a success with an empty list, not an error.
    assert (miss["count"], miss["candidates"]) == (0, [])
    assert miss["skipped_incomplete"] == []


def test_search_never_passes_a_recipe_it_cannot_total(tmp_path) -> None:
    """Rule 12: no filter, and still not a candidate. It is named instead."""
    author(tmp_path, "pizza.yaml", PIZZA_YAML)

    unfiltered = data_of(
        invoke(main, ["search", "--dir", str(tmp_path), "--json"])
    )
    filtered = data_of(
        invoke(
            main,
            ["search", "--dir", str(tmp_path), "--max-kcal", "900", "--json"],
        )
    )
    skipped = [
        {
            "name": "Sourdough Pizza",
            "unresolved": [
                "coles:1: no macro snapshot",
                "coles:2: no macro snapshot",
                "coles:3: no macro snapshot",
            ],
        }
    ]

    assert (unfiltered["candidates"], unfiltered["skipped_incomplete"]) == (
        [],
        skipped,
    )
    assert (filtered["candidates"], filtered["skipped_incomplete"]) == (
        [],
        skipped,
    )


def test_fit_reports_an_unmet_constraint_as_exit_three(tmp_path) -> None:
    pizza(tmp_path)

    result = invoke(
        main,
        [
            "fit",
            "Sourdough Pizza",
            "--max-kcal",
            "300",
            "--min-protein",
            "60",
            "--dir",
            str(tmp_path),
            "--json",
        ],
    )
    payload = failure_of(result)

    assert result.exit_code == 3
    assert payload["data"]["fits"] is False
    assert payload["data"]["gap"]["protein_g"] > 0
    assert payload["error"]["message"]


def test_the_surface_is_five_verbs() -> None:
    """Six domain verbs, plus the two agentcli provides."""
    assert sorted(main.commands) == [
        "fit",
        "guide",
        "resolve",
        "search",
        "serve",
        "share",
        "show",
        "skill",
    ]


def test_store_write_is_the_only_write_path() -> None:
    """A grep, because "one verb writes" is a property of the whole package.

    Tests live beside the modules they cover and write freely to tmp_path, so
    the scan is over shipped modules only. Widening it to the test files
    would make the rule unfalsifiable rather than stricter.
    """
    sources = Path(store.__file__).parent.rglob("*.py")
    writers = {
        path.name
        for path in sources
        if not path.name.endswith("_test.py")
        and path.name != "conftest.py"
        and "store.write(" in path.read_text(encoding="utf-8")
    }

    assert writers == {"resolve.py"}
