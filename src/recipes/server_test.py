"""Tests for the recipes HTTP server and API endpoints."""

import json
import threading
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

from recipes import store
from recipes.cli import main
from recipes.models import Ingredient, Macros, Recipe
from recipes.server import create_server
from recipes.conftest import FakeLookup

PIZZA_LOOKUP = FakeLookup(
    {
        ("coles", "1"): ("Pizza Dough", 268.0, 8.9, 3.1, 49.2),
        ("coles", "2"): ("Passata", 34.0, 1.6, 0.2, 6.4),
        ("coles", "3"): ("Mozzarella", 280.0, 22.0, 21.0, 1.5),
    }
)


def sample_pizza() -> Recipe:
    return Recipe(
        name="Sourdough Pizza",
        servings=2,
        tags=["dinner"],
        notes="Stretch cold, from the edges.\nBake 8 min at max heat.",
        ingredients=[
            Ingredient(
                source="coles",
                id="1",
                grams=475,
                name="Pizza Dough",
                macros=Macros(
                    kcal=268.0, protein=8.9, fat=3.1, carbohydrates=49.2
                ),
            ),
            Ingredient(
                source="coles",
                id="2",
                grams=100,
                name="Passata",
                macros=Macros(
                    kcal=34.0, protein=1.6, fat=0.2, carbohydrates=6.4
                ),
            ),
        ],
    )


@pytest.fixture
def recipe_dir(tmp_path: Path) -> Path:
    recipes = tmp_path / "recipes"
    recipes.mkdir()
    store.write(recipes / "pizza.yaml", sample_pizza())
    return recipes


@pytest.fixture
def running_server(recipe_dir: Path):
    """Run an ephemeral server in a background thread."""
    server = create_server("127.0.0.1", 0, recipe_dir, PIZZA_LOOKUP)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    base_url = f"http://127.0.0.1:{port}"
    try:
        yield base_url, recipe_dir
    finally:
        server.shutdown()
        server.server_close()


def http_request(
    url: str,
    method: str = "GET",
    body: dict[str, Any] | None = None,
) -> tuple[int, dict[str, Any], dict[str, str]]:
    """Helper for HTTP requests returning (status, json_body, headers)."""
    data = (
        json.dumps(body, ensure_ascii=False).encode("utf-8")
        if body is not None
        else None
    )
    req = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json; charset=utf-8")

    try:
        with urllib.request.urlopen(req) as resp:
            status = resp.status
            raw = resp.read()
            headers = dict(resp.headers)
            parsed = json.loads(raw.decode("utf-8")) if raw else {}
            return status, parsed, headers
    except urllib.error.HTTPError as exc:
        status = exc.code
        raw = exc.read()
        headers = dict(exc.headers)
        parsed = json.loads(raw.decode("utf-8")) if raw else {}
        return status, parsed, headers


def test_health_endpoint(running_server) -> None:
    base_url, recipe_dir = running_server
    status, payload, _ = http_request(f"{base_url}/api/health")

    assert status == 200
    assert payload["ok"] is True
    assert payload["recipe_dir"] == str(recipe_dir)


def test_recipes_list_endpoint(running_server) -> None:
    base_url, _ = running_server
    status, payload, _ = http_request(f"{base_url}/api/recipes")

    assert status == 200
    assert isinstance(payload, list)
    assert len(payload) == 1
    assert payload[0]["name"] == "Sourdough Pizza"
    assert payload[0]["kind"] == "recipe"
    assert payload[0]["complete"] is True


def test_recipe_get_endpoint(running_server) -> None:
    base_url, _ = running_server
    status, payload, _ = http_request(
        f"{base_url}/api/recipes/Sourdough%20Pizza"
    )

    assert status == 200
    assert payload["name"] == "Sourdough Pizza"
    assert payload["servings"] == 2
    assert payload["complete"] is True
    assert len(payload["ingredients"]) == 2


def test_recipe_get_missing_404(running_server) -> None:
    base_url, _ = running_server
    status, payload, _ = http_request(
        f"{base_url}/api/recipes/Nonexistent%20Recipe"
    )

    assert status == 404
    assert payload["ok"] is False


def test_valid_put_round_trip(running_server) -> None:
    base_url, _ = running_server
    body = {
        "name": "Quick Toast",
        "servings": 1,
        "ingredients": [
            {
                "source": "coles",
                "id": "1",
                "grams": 100,
            }
        ],
    }

    status, payload, _ = http_request(
        f"{base_url}/api/recipes/Quick%20Toast",
        method="PUT",
        body=body,
    )

    assert status == 200
    assert payload["ok"] is True
    assert payload["name"] == "Quick Toast"

    # Confirm it was written to disk and can be retrieved via GET
    get_status, get_payload, _ = http_request(
        f"{base_url}/api/recipes/Quick%20Toast"
    )
    assert get_status == 200
    assert get_payload["name"] == "Quick Toast"
    assert get_payload["complete"] is True


def test_put_rejected_with_nothing_written(running_server) -> None:
    base_url, recipe_dir = running_server
    initial_files = set(recipe_dir.iterdir())

    body = {
        "name": "Broken Recipe",
        "servings": 1,
        "ingredients": [
            {
                "source": "coles",
                "id": "999",  # unresolvable
                "grams": 100,
            }
        ],
    }

    status, payload, _ = http_request(
        f"{base_url}/api/recipes/Broken%20Recipe",
        method="PUT",
        body=body,
    )

    assert status == 400
    assert payload["ok"] is False
    assert "errors" in payload
    assert len(payload["errors"]) > 0

    # Assert nothing was written to the directory
    assert set(recipe_dir.iterdir()) == initial_files


def test_products_search_endpoint(running_server) -> None:
    base_url, _ = running_server
    status, payload, _ = http_request(f"{base_url}/api/products?q=Passata")

    assert status == 200
    assert isinstance(payload, list)
    assert len(payload) == 1
    assert payload[0]["name"] == "Passata"
    assert payload[0]["macros"]["kcal"] == 34.0

    empty_status, empty_payload, _ = http_request(
        f"{base_url}/api/products?q="
    )
    assert empty_status == 200
    assert empty_payload == []


def test_product_get_endpoint(running_server) -> None:
    base_url, _ = running_server
    status, payload, _ = http_request(f"{base_url}/api/products/coles/1")

    assert status == 200
    assert payload["name"] == "Pizza Dough"
    assert payload["macros"]["kcal"] == 268.0

    missing_status, _, _ = http_request(f"{base_url}/api/products/coles/999")
    assert missing_status == 404


def test_static_files_served_with_correct_mimes(running_server) -> None:
    base_url, _ = running_server

    # GET / serves index.html
    req = urllib.request.Request(f"{base_url}/")
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200
        assert "text/html" in resp.headers.get("Content-Type", "")

    # GET /style.css
    req = urllib.request.Request(f"{base_url}/style.css")
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200
        assert "text/css" in resp.headers.get("Content-Type", "")

    # GET /app.mjs
    req = urllib.request.Request(f"{base_url}/app.mjs")
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200
        assert "javascript" in resp.headers.get("Content-Type", "")


def test_path_traversal_refused(running_server) -> None:
    base_url, _ = running_server

    for bad_path in [
        "/../server_test.py",
        "/%2e%2e/server_test.py",
        "/%2e%2e%2fserver_test.py",
    ]:
        try:
            req = urllib.request.Request(f"{base_url}{bad_path}")
            with urllib.request.urlopen(req):
                pytest.fail(f"Path traversal succeeded for {bad_path}")
        except urllib.error.HTTPError as exc:
            assert exc.code in (403, 404)


def test_no_cors_headers(running_server) -> None:
    base_url, _ = running_server
    _, _, headers = http_request(f"{base_url}/api/health")

    assert "Access-Control-Allow-Origin" not in headers


def test_non_loopback_host_prints_warning(tmp_path: Path, monkeypatch) -> None:
    """Non-loopback host prints a security warning to stderr."""
    runner = CliRunner()
    recipes = tmp_path / "recipes"
    recipes.mkdir()

    # Stub server_forever so CLI doesn't block
    mock_server = type(
        "MockServer",
        (),
        {
            "serve_forever": lambda self: None,
            "server_close": lambda self: None,
        },
    )()
    monkeypatch.setattr(
        "recipes.commands.serve.create_server",
        lambda *args, **kwargs: mock_server,
    )

    result = runner.invoke(
        main,
        ["serve", "--dir", str(recipes), "--host", "0.0.0.0"],
        obj=PIZZA_LOOKUP,
    )
    assert result.exit_code == 0
    assert "Warning: binding to 0.0.0.0" in result.output


def test_a_put_does_not_trust_macros_for_a_referenced_ingredient() -> None:
    """A zero copied out of the product picker must not become a stored fact.

    Pantry's search fills every macro key, using zero for figures nobody
    measured. Posting one back would store it as measured and under-count the
    recipe for good, so resolution re-reads the record instead -- and that path
    refuses a missing macro rather than defaulting it.
    """
    from recipes.server import _intent_only

    posted = {
        "name": "Bowl",
        "ingredients": [
            {
                "source": "coles",
                "id": "1047",
                "grams": 200,
                "macros": {
                    "kcal": 250.0,
                    "protein": 9.0,
                    "fat": 0,
                    "carbohydrates": 0,
                },
            },
            {
                "grams": 50,
                "name": "Hand-written",
                "macros": {
                    "kcal": 100.0,
                    "protein": 1.0,
                    "fat": 2.0,
                    "carbohydrates": 3.0,
                },
            },
        ],
    }

    cleaned = _intent_only(posted)

    # The referenced one loses its macros; resolution derives them.
    assert "macros" not in cleaned["ingredients"][0]
    assert cleaned["ingredients"][0]["grams"] == 200
    # The manual one keeps them: they are the only figures that exist.
    assert cleaned["ingredients"][1]["macros"]["fat"] == 2.0
    # The original is untouched.
    assert "macros" in posted["ingredients"][0]


def test_a_put_re_reads_a_referenced_nutrient_and_keeps_a_manual_one_as_sent() -> (
    None
):
    """Pins the loss in issue #4, so it cannot widen without a red test.

    Plate's editor truncates macros to the four it displays. A referenced
    ingredient pays nothing for that: its macros are dropped here and re-read
    from the record, fibre included. A manual one has no record to re-read, so
    the truncated dict is exactly what gets stored and a hand-written fibre
    figure is gone. That asymmetry is the whole of #4, and the day a
    referenced ingredient starts keeping what a client sent, this fails.
    """
    from recipes.server import _intent_only

    four = {"kcal": 100.0, "protein": 1.0, "fat": 2.0, "carbohydrates": 3.0}
    posted = {
        "name": "Bowl",
        "ingredients": [
            {"source": "coles", "id": "1047", "grams": 200, "macros": four},
            {"grams": 50, "name": "Hand-written", "macros": four},
        ],
    }

    cleaned = _intent_only(posted)

    # Nothing of the client's survives for the referenced one, so a stored
    # `dietary_fiber` is restored by resolution rather than overwritten by this.
    assert "macros" not in cleaned["ingredients"][0]
    # The manual one keeps what was sent, and what was sent has no fibre.
    assert set(cleaned["ingredients"][1]["macros"]) == set(four)
