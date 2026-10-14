"""Flask application: routes only, zero business logic.

All filtering / sorting / pagination / stats live in the injected
``ProductRepository``. The routes only translate between requests and the
repository contract.
"""

from __future__ import annotations

import atexit
import math
import time
from datetime import datetime, timezone
from functools import wraps

from flask import Flask, g, jsonify, request, send_from_directory

from models import Brand, Category, Product, ProductQuery
from repository import EntityNotFoundError, ProductRepository

VALID_SORT_FIELDS = {"name", "price", "rating", "units_sold", "created_at"}


def repo_guard(route_fn):
    """Single exception-mapping block shared by every repository-facing route.

    The priority order is 404, then 400: ``EntityNotFoundError`` maps to 404
    ``{"error": "not found"}``, ``ValueError`` to 400 (its message is
    preserved).
    """

    @wraps(route_fn)
    def wrapper(*args, **kwargs):
        try:
            return route_fn(*args, **kwargs)
        except EntityNotFoundError:
            return jsonify({"error": "not found"}), 404
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

    return wrapper


def _backend_name(repo: ProductRepository) -> str:
    return "mongo" if type(repo).__module__ == "mongo_repository" else "memory"


def _to_iso_utc(dt: datetime) -> str:
    """Serialize a naive-UTC datetime as ISO 8601 with a +00:00 offset."""
    return dt.replace(tzinfo=timezone.utc).isoformat()


def _entity_to_dict(entity: Category | Brand) -> dict | None:
    """Serialize a category / brand entity reference, or ``None`` if absent."""
    if entity is None:
        return None
    return {"id": entity.id, "name": entity.name}


def _product_to_dict(product: Product) -> dict:
    return {
        "id": product.id,
        "name": product.name,
        "description": product.description,
        "category": _entity_to_dict(product.category),
        "brand": _entity_to_dict(product.brand),
        "price": product.price,
        "stock": product.stock,
        "rating": product.rating,
        "units_sold": product.units_sold,
        "created_at": _to_iso_utc(product.created_at),
    }


def _opt_str(args, key: str) -> str | None:
    value = args.get(key)
    return value if value not in (None, "") else None


def _opt_float(args, key: str) -> float | None:
    value = args.get(key)
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None  # ignore an invalid number; never 500


def _opt_int(args, key: str, default: int) -> int:
    value = args.get(key)
    if value in (None, ""):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _opt_bool(args, key: str) -> bool | None:
    value = args.get(key)
    if value in (None, ""):
        return None
    low = value.strip().lower()
    if low in ("true", "1", "yes"):
        return True
    if low in ("false", "0", "no"):
        return False
    return None


def create_app(repository: ProductRepository) -> Flask:
    """Build the Flask app around the injected ``repository``.

    ``ensure_indexes`` runs once at startup; ``close`` is registered to run
    once at process exit via ``atexit`` — never per request.
    """
    app = Flask(__name__)
    repository.ensure_indexes()
    atexit.register(repository.close)

    @app.before_request
    def _note_request_start():
        g.request_start = time.monotonic()

    @app.after_request
    def _inject_page_timing(response):
        """Inject the FR processing-time footer into HTML pages only.

        JSON responses are NEVER modified. File-streamed (pass-through) HTML
        responses are read once and re-sent as plain sequences so the footer
        is present no matter how the page is served; the final ``</body>``
        anchor is preserved (the footer goes right before it).
        """
        if not response.content_type.startswith("text/html"):
            return response
        elapsed_ms = (time.monotonic() - g.request_start) * 1000.0
        label = f"{elapsed_ms:.1f}".replace(".", ",")
        streamed = getattr(response, "direct_passthrough", False)
        data = b"".join(response.response) if streamed else response.get_data()
        html = data.decode("utf-8")
        anchor = html.rfind("</body>")
        if anchor == -1:
            if streamed:
                response.set_data(data)
            return response
        footer = f'<footer class="page-timing">Générée en {label} ms</footer>'
        response.set_data((html[:anchor] + footer + html[anchor:]).encode("utf-8"))
        return response

    @app.get("/meta")
    def meta():
        return jsonify(
            {
                "backend": _backend_name(repository),
                "product_count": repository.list_products(ProductQuery(page_size=1)).total,
            }
        )

    @app.get("/")
    def index():
        return send_from_directory(app.static_folder, "index.html")

    @app.get("/categories")
    def categories_page():
        return send_from_directory(app.static_folder, "categories.html")

    @app.get("/brands")
    def brands_page():
        return send_from_directory(app.static_folder, "brands.html")

    @app.post("/api/products")
    @repo_guard
    def create_product():
        payload = request.get_json(silent=True)
        if payload is None or not isinstance(payload, dict):
            raise ValueError("invalid JSON body")
        product = Product.from_dict(payload)
        created = repository.create_product(product)
        response = jsonify(_product_to_dict(created))
        response.status_code = 201
        response.headers["Location"] = f"/api/products/{created.id}"
        return response

    @app.get("/api/products/stats")
    def stats():
        s = repository.get_stats()
        return jsonify(
            {
                "total": s.total,
                "average_price": s.average_price,
                "by_category": {
                    cat: {
                        "count": cs.count,
                        "average_price": cs.average_price,
                        "total_value": cs.total_value,
                    }
                    for cat, cs in s.by_category.items()
                },
            }
        )

    @app.get("/api/products")
    def list_products():
        args = request.args
        sort_field = args.get("sort_field", "created_at")
        if sort_field not in VALID_SORT_FIELDS:
            return jsonify({"error": f"invalid sort_field {sort_field!r}"}), 400

        price_min = _opt_float(args, "price_min")
        price_max = _opt_float(args, "price_max")
        min_rating = _opt_float(args, "min_rating")
        for value in (price_min, price_max, min_rating):
            if value is not None and not math.isfinite(value):
                return jsonify({"error": "numeric bounds must be finite"}), 400

        query = ProductQuery(
            category=_opt_str(args, "category"),
            brand=_opt_str(args, "brand"),
            price_min=price_min,
            price_max=price_max,
            min_rating=min_rating,
            in_stock=_opt_bool(args, "in_stock"),
            search_text=_opt_str(args, "search_text"),
            sort_field=sort_field,
            sort_ascending=_opt_bool(args, "sort_ascending") or False,
            page=_opt_int(args, "page", 1),
            page_size=_opt_int(args, "page_size", 20),
        )
        page_obj = repository.list_products(query)
        return jsonify(
            {
                "items": [_product_to_dict(p) for p in page_obj.items],
                "total": page_obj.total,
                "page": page_obj.page,
                "page_size": page_obj.page_size,
                "total_pages": page_obj.total_pages,
            }
        )

    @app.get("/api/products/<string:product_id>")
    @repo_guard
    def get_product(product_id: str):
        product = repository.get_product(product_id)
        if product is None:
            raise EntityNotFoundError(f"product id {product_id!r} not found")
        return jsonify(_product_to_dict(product))

    @app.put("/api/products/<string:product_id>")
    @repo_guard
    def update_product(product_id: str):
        # Error priority is 404 over 400: an unknown product is reported even
        # when the body is also invalid, so existence is checked first.
        stored = repository.get_product(product_id)
        if stored is None:
            raise EntityNotFoundError(f"product id {product_id!r} not found")
        payload = request.get_json(silent=True)
        if payload is None or not isinstance(payload, dict):
            raise ValueError("invalid JSON body")
        # Boundary validation happens HERE: the repository trusts the
        # typed product and does not re-validate.
        normalized = Product.validate_payload(payload)
        updated = repository.update_product(
            Product(id=stored.id, created_at=stored.created_at, **normalized)
        )
        return jsonify(_product_to_dict(updated))

    @app.delete("/api/products/<string:product_id>")
    @repo_guard
    def delete_product(product_id: str):
        repository.delete_product(product_id)
        return "", 204

    # Entities are NEVER created through these routes: they are created
    # implicitly when products are saved with an unknown name.

    @app.get("/api/categories")
    def list_categories():
        return jsonify([_entity_to_dict(c) for c in repository.list_categories()])

    @app.get("/api/brands")
    def list_brands():
        return jsonify([_entity_to_dict(b) for b in repository.list_brands()])

    def _rename_entity(entity_id: str, rename_entity) -> Category | Brand:
        """Shared PUT body handling for one entity kind; raises mapped errors."""
        body = request.get_json(silent=True)
        if body is None:
            raise ValueError("invalid JSON body")
        if not isinstance(body, dict):
            raise ValueError("body must be a JSON object")
        if "name" not in body:
            raise ValueError("name is required")
        name = body["name"]
        if not isinstance(name, str):
            raise ValueError("name must be a string")
        return rename_entity(entity_id, name)

    @app.put("/api/categories/<string:category_id>")
    @repo_guard
    def rename_category(category_id: str):
        # Error priority is 404, then 400: existence first, then the body shape.
        if repository.get_category(category_id) is None:
            raise EntityNotFoundError(f"category id {category_id!r} not found")
        entity = _rename_entity(category_id, repository.rename_category)
        return jsonify(_entity_to_dict(entity))

    @app.delete("/api/categories/<string:category_id>")
    @repo_guard
    def delete_category(category_id: str):
        removed_from = repository.delete_category(category_id)
        return jsonify({"removed_from": removed_from})

    @app.put("/api/brands/<string:brand_id>")
    @repo_guard
    def rename_brand(brand_id: str):
        if repository.get_brand(brand_id) is None:
            raise EntityNotFoundError(f"brand id {brand_id!r} not found")
        entity = _rename_entity(brand_id, repository.rename_brand)
        return jsonify(_entity_to_dict(entity))

    @app.delete("/api/brands/<string:brand_id>")
    @repo_guard
    def delete_brand(brand_id: str):
        removed_from = repository.delete_brand(brand_id)
        return jsonify({"removed_from": removed_from})

    return app
