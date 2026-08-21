"""Shared fakes. The product database is injected, so tests own it."""

import json

import pytest
from click.testing import CliRunner, Result

from recipes.models import Product


@pytest.fixture(autouse=True)
def no_ambient_dotenv(monkeypatch) -> None:
    """Keep the developer's own `.env` out of every test.

    `load_dotenv()` searches parent directories, so a `.env` anywhere above
    the checkout silently refills variables a test just cleared. That is how
    a viewer test passed on one machine and failed on another.
    """
    monkeypatch.setattr("recipes.viewer.load_dotenv", lambda: None)


class FakeLookup:
    """A product database of exactly the rows a test declares.

    Anything not declared misses, which is the case rule 12 is about.
    """

    def __init__(
        self,
        rows: dict[tuple[str, str], tuple[str, float, float, float, float]],
    ) -> None:
        self.rows = rows
        self.calls: list[tuple[str, str]] = []

    def lookup(self, source: str, id: str) -> Product | None:
        self.calls.append((source, id))
        row = self.rows.get((source, id))
        if row is None:
            return None

        name, kcal, protein, fat, carbs = row
        return Product(
            name=name,
            source=source,
            id=id,
            kcal=kcal,
            protein=protein,
            fat=fat,
            carbs=carbs,
        )

    def search(
        self, query: str, limit: int = 10, remote: bool = False
    ) -> list[dict]:
        results = []
        q = query.lower()
        for (source, pid), (name, kcal, p, f, c) in self.rows.items():
            if q in name.lower() or q in pid.lower():
                results.append(
                    {
                        "source": source,
                        "id": pid,
                        "name": name,
                        "brand": "",
                        "macros": {
                            "kcal": kcal,
                            "protein": p,
                            "fat": f,
                            "carbs": c,
                        },
                    }
                )
                if len(results) >= limit:
                    break
        return results


def invoke(command, args: list[str], *, lookup=None) -> Result:
    """Run a command with the injected lookup click would otherwise build."""
    return CliRunner().invoke(
        command, args, obj=lookup or FakeLookup({}), catch_exceptions=False
    )


def data_of(result: Result) -> dict:
    """Unwrap agentcli's success envelope, asserting what it promises."""
    envelope = json.loads(result.output)
    assert envelope["ok"] is True, envelope

    return envelope["data"]


def failure_of(result: Result) -> dict:
    """The whole failure envelope: `error.message` and any `data` beside it."""
    envelope = json.loads(result.output)
    assert envelope["ok"] is False, envelope

    return envelope
