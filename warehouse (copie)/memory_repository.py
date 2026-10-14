"""In-memory backend: the CONTRACTUALLY NAIVE reference implementation.

``InMemoryProductRepository`` fulfils the shared contract
(``repository.ProductRepository``) with correctness only: one dict keyed
by id per entity kind, no secondary index structures of any kind. It is
the behavioral reference that the MongoDB exercise
(``mongo_repository.py``) and the test suite are run against.

The private helpers ``_slug`` and ``_entity_name`` belong to this backend
only: the SLUG id format they define is a reference detail, never part of
the contract.
"""

from __future__ import annotations

import logging
import re
import uuid
from dataclasses import replace

from models import Brand, CatalogStats, Category, CategoryStats, Product, ProductPage, ProductQuery
from repository import EntityNotFoundError, ProductRepository

LOGGER = logging.getLogger(__name__)


def _slug(name: str) -> str:
    """Slug for an in-memory reference entity id (reference detail, not contract).

    Lowercase only, NO unicode fold. Runs of characters outside ``[a-z0-9]``
    collapse into a single hyphen; leading and trailing hyphens are stripped.
    A purely punctuation name yields the empty string; the caller replaces it
    with the opaque ``"u-" + uuid4().hex[:8]`` id.
    """
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _entity_name(entity: Category | Brand | None) -> str | None:
    """Return the name of a category / brand entity, or ``None`` if absent."""
    return entity.name if entity is not None else None


class InMemoryProductRepository(ProductRepository):
    """Contractually naive reference implementation.

    ONE dict keyed by id for O(1) get/delete. ``list_products`` is a linear
    scan + filter + ``sorted()`` (with the id tiebreak) + slice. There are NO
    secondary index structures of any kind. Each entity kind is owned by a
    dict holding FROZEN entities by id, plus a name-to-id map (a duplicate
    name is legal; the map keeps the last writer); ids follow the SLUG rule
    (see :func:`_slug`) and, once created, are frozen. A rename replaces the
    stored entity with a NEW FROZEN entity (same id, new name) and re-points
    the stored products naively (O(n)); snapshots already in the caller's
    hand keep the old entity, which is the observable snapshot semantics
    shared with the Mongo backend. ``ensure_indexes`` and ``close`` are
    no-ops.
    """

    def __init__(self) -> None:
        self._by_id: dict[str, Product] = {}
        self._categories: dict[str, Category] = {}
        self._category_names: dict[str, str] = {}  # name -> id
        self._brands: dict[str, Brand] = {}
        self._brand_names: dict[str, str] = {}  # name -> id

    def _get_or_create_entity(
        self,
        name: str,
        factory: type[Category] | type[Brand],
        by_id: dict[str, Category] | dict[str, Brand],
        by_name: dict[str, str],
    ) -> Category | Brand:
        """Return the frozen entity for ``name``, creating it on first sight.

        A known name always reuses its entity (an id is frozen at creation
        and a rename never re-sluggs). A new name takes its slug; a slug
        already held by ANOTHER name gets the ``-2``, ``-3``, ... suffix in
        creation order; a name whose slug is empty (pure punctuation) takes
        the opaque ``"u-" + uuid4().hex[:8]`` id.
        """
        existing_id = by_name.get(name)
        if existing_id is not None:
            return by_id[existing_id]
        slug = _slug(name)
        base = slug if slug else "u-" + uuid.uuid4().hex[:8]
        candidate = base
        suffix = 1
        while candidate in by_id:
            suffix += 1
            candidate = f"{base}-{suffix}"
        entity = factory(id=candidate, name=name)
        by_id[candidate] = entity
        by_name[name] = candidate
        return entity

    def _bind_category(self, entity: Category | None) -> Category | None:
        """Re-bind ``entity`` to its canonical frozen entity (or ``None``)."""
        if entity is None:
            return None
        return self._get_or_create_entity(
            entity.name, Category, self._categories, self._category_names
        )

    def _bind_brand(self, entity: Brand | None) -> Brand | None:
        """Re-bind ``entity`` to its canonical frozen entity (or ``None``)."""
        if entity is None:
            return None
        return self._get_or_create_entity(entity.name, Brand, self._brands, self._brand_names)

    def create_product(self, product: Product) -> Product:
        LOGGER.info("create_product(%r, %s, %d)", product.name, product.price, product.stock)
        stored = replace(
            product,
            id=uuid.uuid4().hex,
            category=self._bind_category(product.category),
            brand=self._bind_brand(product.brand),
        )
        self._by_id[stored.id] = stored
        return stored

    def create_products(self, products: list[Product]) -> list[Product]:
        LOGGER.info("create_products(%d)", len(products))
        # The shared name maps guarantee that a name referenced anywhere in
        # the batch is registered exactly once: one entity per name.
        return [self.create_product(product) for product in products]

    def get_product(self, product_id: str) -> Product | None:
        LOGGER.info("get_product(%r)", product_id)
        # The stored product already carries its frozen entities: the fetch
        # returns them as-is (snapshot semantics, as on the Mongo backend).
        return self._by_id.get(product_id)

    def update_product(self, product: Product) -> Product:
        LOGGER.info("update_product(%r, %r)", product.id, product.name)
        existing = self._by_id.get(product.id)
        if existing is None:
            raise EntityNotFoundError(f"product id {product.id!r} not found")
        # The stored id and created_at are preserved; every mutable field is
        # replaced. The entity ids carried by the argument are ignored: the
        # binding is by name (auto-creating an unknown name, detaching on
        # None). No re-validation: the typed product is trusted.
        stored = replace(
            existing,
            name=product.name,
            description=product.description,
            category=self._bind_category(product.category),
            brand=self._bind_brand(product.brand),
            price=product.price,
            stock=product.stock,
            rating=product.rating,
            units_sold=product.units_sold,
        )
        self._by_id[product.id] = stored
        return stored

    def list_products(self, query: ProductQuery) -> ProductPage:
        LOGGER.info("list_products(%r)", query)
        items = list(self._by_id.values())

        # Filters are by NAME: a product whose category / brand is None can
        # never match a name filter (the "without a category" filter does not
        # exist in the query contract).
        if query.category is not None:
            items = [p for p in items if _entity_name(p.category) == query.category]
        if query.brand is not None:
            items = [p for p in items if _entity_name(p.brand) == query.brand]
        if query.price_min is not None:
            items = [p for p in items if p.price >= query.price_min]
        if query.price_max is not None:
            items = [p for p in items if p.price <= query.price_max]
        if query.min_rating is not None:
            items = [p for p in items if p.rating >= query.min_rating]
        if query.in_stock is not None:
            if query.in_stock:
                items = [p for p in items if p.stock > 0]
            else:
                items = [p for p in items if p.stock == 0]
        if query.search_text is not None:
            needle = query.search_text.lower()
            items = [
                p for p in items if needle in p.name.lower() or needle in p.description.lower()
            ]

        total = len(items)

        # Tiebreak contract: sort by id ascending first (stable), then by the
        # requested field; equal field values keep their id-ascending order.
        items = sorted(items, key=lambda p: p.id)
        items = sorted(
            items,
            key=lambda p: getattr(p, query.sort_field),
            reverse=not query.sort_ascending,
        )

        page_size = max(1, min(100, query.page_size))
        page = max(1, query.page)
        total_pages = (total + page_size - 1) // page_size if total else 0
        start = (page - 1) * page_size
        end = start + page_size
        return ProductPage(
            items=items[start:end],
            total=total,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
        )

    def delete_product(self, product_id: str) -> None:
        LOGGER.info("delete_product(%r)", product_id)
        if self._by_id.pop(product_id, None) is None:
            raise EntityNotFoundError(f"product id {product_id!r} not found")

    def get_stats(self) -> CatalogStats:
        LOGGER.info("get_stats()")
        products = list(self._by_id.values())
        total = len(products)
        if total == 0:
            return CatalogStats(total=0, average_price=0.0, by_category={})

        average_price = sum(p.price for p in products) / total

        # ``by_category`` contains ONLY products that have a category, keyed
        # by the current (registry-truth) name in codepoint order. Products
        # without a category are excluded from ``by_category`` but stay in
        # ``total`` / ``average_price``.
        groups: dict[str, list[Product]] = {}
        for p in products:
            if p.category is None:
                continue
            groups.setdefault(p.category.name, []).append(p)

        by_category: dict[str, CategoryStats] = {}
        for category in sorted(groups):
            group = groups[category]
            count = len(group)
            avg_price = sum(p.price for p in group) / count
            total_value = sum(p.price * p.stock for p in group)
            by_category[category] = CategoryStats(
                count=count, average_price=avg_price, total_value=total_value
            )

        return CatalogStats(
            total=total,
            average_price=average_price,
            by_category=by_category,
        )

    def list_categories(self) -> list[Category]:
        LOGGER.info("list_categories()")
        return sorted(self._categories.values(), key=lambda c: c.name)

    def get_category(self, category_id: str) -> Category | None:
        LOGGER.info("get_category(%r)", category_id)
        return self._categories.get(category_id)

    def rename_category(self, category_id: str, new_name: str) -> Category:
        LOGGER.info("rename_category(%r, %r)", category_id, new_name)
        trimmed = new_name.strip()
        entity = self._categories.get(category_id)
        if entity is None:
            raise EntityNotFoundError(f"category id {category_id!r} not found")
        if entity.name == trimmed:
            return entity
        # New FROZEN entity, SAME id; the name map is re-anchored and every
        # stored product is re-pointed naively (O(n)). Snapshots already in
        # the caller's hand keep the old entity (snapshot semantics).
        renamed = Category(id=entity.id, name=trimmed)
        self._categories[category_id] = renamed
        del self._category_names[entity.name]
        self._category_names[trimmed] = category_id
        for product in self._by_id.values():
            if product.category is not None and product.category.id == category_id:
                self._by_id[product.id] = replace(product, category=renamed)
        return renamed

    def delete_category(self, category_id: str) -> int:
        LOGGER.info("delete_category(%r)", category_id)
        entity = self._categories.get(category_id)
        if entity is None:
            raise EntityNotFoundError(f"category id {category_id!r} not found")
        affected = 0
        for product in self._by_id.values():
            if product.category is not None and product.category.id == category_id:
                self._by_id[product.id] = replace(product, category=None)
                affected += 1
        del self._categories[category_id]
        del self._category_names[entity.name]
        return affected

    def list_brands(self) -> list[Brand]:
        LOGGER.info("list_brands()")
        return sorted(self._brands.values(), key=lambda b: b.name)

    def get_brand(self, brand_id: str) -> Brand | None:
        LOGGER.info("get_brand(%r)", brand_id)
        return self._brands.get(brand_id)

    def rename_brand(self, brand_id: str, new_name: str) -> Brand:
        LOGGER.info("rename_brand(%r, %r)", brand_id, new_name)
        trimmed = new_name.strip()
        entity = self._brands.get(brand_id)
        if entity is None:
            raise EntityNotFoundError(f"brand id {brand_id!r} not found")
        if entity.name == trimmed:
            return entity
        renamed = Brand(id=entity.id, name=trimmed)
        self._brands[brand_id] = renamed
        del self._brand_names[entity.name]
        self._brand_names[trimmed] = brand_id
        for product in self._by_id.values():
            if product.brand is not None and product.brand.id == brand_id:
                self._by_id[product.id] = replace(product, brand=renamed)
        return renamed

    def delete_brand(self, brand_id: str) -> int:
        LOGGER.info("delete_brand(%r)", brand_id)
        entity = self._brands.get(brand_id)
        if entity is None:
            raise EntityNotFoundError(f"brand id {brand_id!r} not found")
        affected = 0
        for product in self._by_id.values():
            if product.brand is not None and product.brand.id == brand_id:
                self._by_id[product.id] = replace(product, brand=None)
                affected += 1
        del self._brands[brand_id]
        del self._brand_names[entity.name]
        return affected

    def ensure_indexes(self) -> None:
        """No-op: the in-memory backend has no indexes to build."""
        LOGGER.info("ensure_indexes()")

    def close(self) -> None:
        """No-op: the in-memory backend holds no external resources."""
        LOGGER.info("close()")
