"""One recipe, one YAML file, in a directory the user chooses.

Recipes are private user data, so they live under XDG config (or a `--dir`
pointing at a private git repo) and never inside a checkout.

Identity is the `name:` field, not the filename, so lookups scan the directory
and match on it: hand-editing `name:` is how a recipe is renamed, and tens of
small files make the scan free. There is deliberately no revision log, because
git already does that job: two revisions of a recipe are two commits.
"""

import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from mealtime_nutrients import CORE_NUTRIENTS, OPTIONAL_NUTRIENTS

from recipes.macros import compact_number, figure_numbers, parse_servings
from recipes.models import (
    PRODUCT_SOURCES,
    Ingredient,
    Macros,
    Recipe,
    to_decimal,
)

SUFFIX = ".yaml"

# Readable in `ls`, with room left for the digest inside the name limit.
_SLUG_LIMIT = 48


class StoreError(Exception):
    """A recipe file that cannot be read, or a name that cannot be stored."""


@dataclass(frozen=True)
class Stored:
    """A recipe and the file it came from.

    The path travels with the recipe because identity is the `name:` field and
    not the filename: a write has to go back where it came from, and an agent
    that edits a recipe by hand has to be told which file to open.
    """

    path: Path
    recipe: Recipe


def default_dir(
    env: dict[str, str] | None = None, home: Path | None = None
) -> Path:
    """`$XDG_CONFIG_HOME/recipes`, or `~/.config/recipes`."""
    environ = os.environ if env is None else env
    base = environ.get("XDG_CONFIG_HOME") or ""
    root = Path(base) if base else (home or Path.home()) / ".config"
    return root / "recipes"


def recipe_key(name: str) -> str:
    """The identity of a recipe: its name, trimmed and case-folded.

    Two files whose names differ only in whitespace or case are two files
    claiming one recipe, which is reported rather than resolved.
    """
    return " ".join(name.split()).casefold()


def filename_for(name: str) -> str:
    """A suggested filename for a new recipe. Cosmetic, never looked up.

    Nothing resolves a recipe through this: the slug is for humans reading a
    directory listing, and the digest of the identity key only keeps two names
    that slug alike from landing on one file.
    """
    key = recipe_key(name)
    if not key:
        raise StoreError("a recipe needs a name")

    slug = re.sub(r"[^a-z0-9]+", "-", key).strip("-")[:_SLUG_LIMIT]
    digest = hashlib.sha256(key.encode()).hexdigest()[:8]
    return f"{slug or 'recipe'}-{digest}{SUFFIX}"


def path_for(directory: Path, name: str) -> Path:
    """Where a new recipe file may go. Always directly inside `directory`."""
    return directory / filename_for(name)


def _nutrients_from(raw: dict[str, Any], ref: str) -> Macros | None:
    """Read a snapshot, or report its absence. Never infer a zero."""
    if not any(raw.get(key) is not None for key in CORE_NUTRIENTS):
        return None

    missing = [key for key in CORE_NUTRIENTS if raw.get(key) is None]
    if missing:
        raise StoreError(f"{ref}: nutrients missing {', '.join(missing)}")

    # Read as decimals: a file says `0.28`, and that is the figure it means.
    values = {key: to_decimal(raw[key]) for key in CORE_NUTRIENTS}

    # An optional nutrient the file omits stays unstated, never a zero.
    for key in OPTIONAL_NUTRIENTS:
        if raw.get(key) is not None:
            values[key] = to_decimal(raw[key])

    # `.nan` and `.inf` are readable YAML floats and crash `round_js` later.
    unusable = [key for key, value in values.items() if not value.is_finite()]
    if unusable:
        raise StoreError(f"{ref}: nutrients not finite: {', '.join(unusable)}")

    return Macros(**values)


def _ingredient_from(raw: Any) -> Ingredient:
    """Read one ingredient. No name or macros means "not yet resolved".

    That is the shape a person or an agent writes by hand — a reference and an
    amount, nothing else — so it is valid input, not a malformed record.
    """
    if not isinstance(raw, dict):
        raise StoreError(f"ingredient must be a mapping: {raw!r}")

    ref = f"{raw.get('source')}:{raw.get('id')}"
    try:
        grams = float(raw["grams"])
    except (KeyError, TypeError, ValueError) as exc:
        raise StoreError(f"{ref}: unreadable grams") from exc

    # Refused at ingress rather than stored as a reference nothing resolves.
    source = str(raw.get("source") or "manual")
    if source not in PRODUCT_SOURCES:
        allowed = ", ".join(PRODUCT_SOURCES)
        raise StoreError(f"{ref}: unknown source, expected one of {allowed}")

    return Ingredient(
        source=source,
        id=str(raw.get("id") or ""),
        grams=grams,
        name=str(raw["name"]) if raw.get("name") else None,
        macros=_nutrients_from(raw, ref),
    )


def recipe_from_mapping(raw: Any) -> Recipe:
    """Build a recipe from parsed YAML, refusing anything unreadable."""
    if not isinstance(raw, dict):
        raise StoreError("a recipe file must contain a mapping")

    name = str(raw.get("name") or "").strip()
    if not name:
        raise StoreError("a recipe file must carry a name")

    return Recipe(
        name=name,
        servings=parse_servings(raw.get("servings", 1)),
        ingredients=[
            _ingredient_from(item) for item in raw.get("ingredients") or []
        ],
        tags=[str(tag) for tag in raw.get("tags") or []],
        notes=str(raw.get("notes") or ""),
        source_url=str(raw.get("source_url") or ""),
    )


def mapping_of(recipe: Recipe) -> dict[str, Any]:
    """The YAML shape."""
    mapping: dict[str, Any] = {
        "name": recipe.name,
        "servings": parse_servings(recipe.servings),
    }
    if recipe.tags:
        mapping["tags"] = list(recipe.tags)
    if recipe.notes:
        mapping["notes"] = recipe.notes
    if recipe.source_url:
        mapping["source_url"] = recipe.source_url

    mapping["ingredients"] = [
        _ingredient_mapping(item) for item in recipe.ingredients
    ]
    return mapping


def _ingredient_mapping(item: Ingredient) -> dict[str, Any]:
    mapping: dict[str, Any] = {
        "source": item.source,
        "id": item.id,
        "grams": compact_number(item.grams),
    }
    if item.name:
        mapping["name"] = item.name

    # Omitted rather than zeroed, so unresolved reads apart from calorie-free.
    if item.macros is not None:
        mapping.update(figure_numbers(item.macros.stated()))

    return mapping


class _Dumper(yaml.SafeDumper):
    """SafeDumper that writes multi-line text as a literal block.

    Notes are method text. `"line one\\nline two"` on one escaped line is
    unreadable and undiffable, which is the whole reason YAML replaced JSONL.
    """


def _represent_str(dumper: yaml.SafeDumper, value: str) -> yaml.ScalarNode:
    style = "|" if "\n" in value else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", value, style=style)


_Dumper.add_representer(str, _represent_str)


def dump_recipe(recipe: Recipe) -> str:
    """Serialize one recipe. Key order is authored, not alphabetical."""
    return yaml.dump(
        mapping_of(recipe),
        Dumper=_Dumper,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
        width=79,
    )


def load_recipe(path: Path) -> Recipe:
    """Read one recipe file."""
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise StoreError(f"{path.name}: {exc}") from exc

    return recipe_from_mapping(raw)


def _entries(directory: Path) -> list[Stored]:
    """Every readable recipe file, in filename order."""
    if not directory.is_dir():
        return []

    return [
        Stored(path=path, recipe=load_recipe(path))
        for path in sorted(directory.glob(f"*{SUFFIX}"))
    ]


def _sole(matches: list[Stored], name: str) -> Stored:
    """The single file claiming a name, or a refusal naming every claimant.

    Picking one silently would answer a question about macros with whichever
    file the filesystem listed first.
    """
    if len(matches) > 1:
        paths = ", ".join(str(match.path) for match in matches)
        raise StoreError(
            f"{name}: more than one file claims this name: {paths}"
        )

    return matches[0]


def _one(matches: list[Stored], name: str) -> Stored | None:
    """`_sole`, but no file claiming the name is a miss, not an error."""
    return _sole(matches, name) if matches else None


def load_all(directory: Path) -> list[Stored]:
    """Every recipe in the directory, ordered by identity for stable output."""
    grouped: dict[str, list[Stored]] = {}
    for entry in _entries(directory):
        grouped.setdefault(recipe_key(entry.recipe.name), []).append(entry)

    # Every group came from an appended entry, so none of them is empty.
    return [
        _sole(matches, matches[0].recipe.name)
        for _, matches in sorted(grouped.items())
    ]


def find(directory: Path, name: str) -> Stored | None:
    """Look a recipe up by the `name:` field of every file, or return None."""
    key = recipe_key(name)
    matches = [
        entry
        for entry in _entries(directory)
        if recipe_key(entry.recipe.name) == key
    ]
    return _one(matches, name)


def require(directory: Path, name: str) -> Stored:
    """`find`, for callers that have nothing useful to do with a miss."""
    stored = find(directory, name)
    if stored is None:
        raise StoreError(f"recipe not found: {name}")

    return stored


def write(path: Path, recipe: Recipe) -> bool:
    """Write one recipe if the bytes would differ. Reports whether it did.

    Identical bytes are not rewritten: `resolve` is idempotent, and touching a
    git-tracked file for nothing costs a diff a human has to read.

    Written beside the target and renamed over it: a crash mid-write must not
    leave half a recipe where a whole one was, and rename is atomic.
    """
    text = dump_recipe(recipe)
    try:
        if path.is_file() and path.read_text(encoding="utf-8") == text:
            return False

        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
        temporary.write_text(text, encoding="utf-8")
        os.replace(temporary, path)
    except OSError as exc:
        raise StoreError(f"{path.name}: {exc}") from exc

    return True
