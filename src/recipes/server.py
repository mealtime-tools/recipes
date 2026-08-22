"""HTTP server and API handler for recipes and plate.

Serves plate's frontend assets and provides the local JSON API for recipes
and products. No auth or CORS: designed for loopback or LAN use.
"""

import http.server
import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

import plate

from recipes import store
from recipes.commands.search import _candidate_of
from recipes.models import ProductLookup
from recipes.render import describe
from recipes.resolve import resolve_and_write

MIME_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
}


def resolve_static_path(root: Path, url_path: str) -> Path | None:
    """Resolve a URL path against root, strictly preventing path traversal.

    Percent-encoded components and relative hops are resolved against root
    and refused if they escape the asset root.
    """
    clean_path = unquote(url_path).split("?", 1)[0].split("#", 1)[0]
    rel = os.path.normpath(clean_path.lstrip("/"))

    if rel.startswith("..") or "/../" in rel or rel == "..":
        return None

    target = (root / rel).resolve()
    root_resolved = root.resolve()

    if target != root_resolved and not str(target).startswith(
        str(root_resolved) + os.sep
    ):
        return None

    if target.is_dir():
        index = target / "index.html"
        if index.is_file():
            return index

    if target.is_file():
        return target

    return None


def _intent_only(raw: dict) -> dict:
    """Drop macros a client sent for an ingredient that names a product.

    Search results carry every macro key with unmeasured ones as zero, so a
    figure copied out of the picker and posted back would be stored as a
    measured zero and quietly under-count the recipe. Resolution reads the
    record itself, which refuses rather than defaults, so the safe move is to
    let it do that.

    An ingredient with no reference is a manual entry: its macros are the only
    ones that exist, and they are kept.

    KNOWN LOSS: kept verbatim means kept as sent. Plate's editor truncates
    macros to the four it displays, so a manual ingredient whose YAML was
    hand-written with a fibre figure loses it on a save through the editor.
    A referenced ingredient does not: its macros are dropped here and re-read
    from the record. Not repaired here because repairing it means merging the
    client's macros with the stored ones, and a client that meant to change a
    figure is indistinguishable from one that never had it. See issue #4.
    """
    items = raw.get("ingredients")
    if not isinstance(items, list):
        return raw

    cleaned = []
    for item in items:
        if not isinstance(item, dict):
            cleaned.append(item)
            continue

        referenced = bool(item.get("source")) and bool(item.get("id"))
        cleaned.append(
            {k: v for k, v in item.items() if k != "macros"}
            if referenced
            else item
        )

    return {**raw, "ingredients": cleaned}


class RecipeRequestHandler(http.server.BaseHTTPRequestHandler):
    """Handles HTTP requests for plate assets and the /api/ endpoints."""

    directory: Path
    lookup: ProductLookup
    assets_dir: Path

    def _send_json(self, data: Any, status: int = 200) -> None:
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _send_error_json(
        self, message: str, status: int = 400, errors: list[str] | None = None
    ) -> None:
        body: dict[str, Any] = {
            "ok": False,
            "error": {"message": message},
        }
        if errors is not None:
            body["errors"] = errors
        self._send_json(body, status=status)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/health":
            self._send_json({"ok": True, "recipe_dir": str(self.directory)})
            return

        if path == "/api/products":
            params = parse_qs(parsed.query)
            q = params.get("q", [""])[0]
            remote = params.get("remote", ["false"])[0].lower() in (
                "1",
                "true",
            )
            if not q.strip():
                self._send_json([])
                return

            if hasattr(self.lookup, "search"):
                results = self.lookup.search(q, remote=remote)
            else:
                results = []
            self._send_json(results)
            return

        if path.startswith("/api/products/"):
            rest = path[len("/api/products/") :].strip("/")
            source, _, product_id = rest.partition("/")
            source, product_id = unquote(source), unquote(product_id)
            product = self.lookup.lookup(source, product_id)
            if product is None:
                self._send_error_json("product not found", status=404)
                return
            self._send_json(
                product.as_dict()
                if hasattr(product, "as_dict")
                else {
                    "source": source,
                    "id": product_id,
                    "name": product.name,
                    "brand": getattr(product, "brand", ""),
                    "macros": product.macros().as_dict(),
                }
            )
            return

        if path == "/api/recipes":
            candidates = [
                _candidate_of(stored)
                for stored in store.load_all(self.directory)
            ]
            self._send_json(candidates)
            return

        if path.startswith("/api/recipes/"):
            name = unquote(path[len("/api/recipes/") :])
            stored = store.find(self.directory, name)
            if stored is None:
                self._send_error_json(f"recipe not found: {name}", status=404)
                return
            self._send_json(
                describe(stored.recipe) | {"path": str(stored.path)}
            )
            return

        # Static file handling
        unquoted = unquote(path)
        if ".." in unquoted or "/../" in unquoted:
            self.send_response(403)
            self.end_headers()
            return

        target = resolve_static_path(self.assets_dir, path)
        if target is None or not target.is_file():
            self.send_response(404)
            self.end_headers()
            return

        ext = target.suffix.lower()
        mime = MIME_TYPES.get(ext, "application/octet-stream")
        try:
            body = target.read_bytes()
        except OSError:
            self.send_response(404)
            self.end_headers()
            return

        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_PUT(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path

        if not path.startswith("/api/recipes/"):
            self._send_error_json("not found", status=404)
            return

        name = unquote(path[len("/api/recipes/") :])
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)

        try:
            raw = json.loads(body.decode("utf-8"))
            if not isinstance(raw, dict):
                self._send_error_json("body must be a JSON object", status=400)
                return

            if not raw.get("name"):
                raw["name"] = name

            recipe = store.recipe_from_mapping(_intent_only(raw))
        except (
            json.JSONDecodeError,
            store.StoreError,
            ValueError,
            KeyError,
            TypeError,
        ) as exc:
            self._send_error_json(str(exc), status=400)
            return

        # Stored path is reused if the recipe already exists under name.
        stored = store.find(self.directory, name)
        file_path = (
            stored.path
            if stored
            else store.path_for(self.directory, recipe.name)
        )

        outcome, written = resolve_and_write(file_path, recipe, self.lookup)

        if outcome.errors:
            self._send_json(
                {"ok": False, "errors": outcome.errors}, status=400
            )
            return

        self._send_json(
            {
                "ok": True,
                "name": recipe.name,
                "path": str(file_path),
                "written": written,
            },
            status=200,
        )

    def log_message(self, format: str, *args: Any) -> None:
        """Suppress default stderr request logging."""


def create_server(
    host: str,
    port: int,
    directory: Path,
    lookup: ProductLookup,
    assets_dir: Path | None = None,
) -> http.server.HTTPServer:
    """Build the HTTP server instance bound to (host, port)."""
    assets = assets_dir or plate.assets_dir()

    class Handler(RecipeRequestHandler):
        pass

    Handler.directory = directory
    Handler.lookup = lookup
    Handler.assets_dir = assets

    return http.server.HTTPServer((host, port), Handler)
