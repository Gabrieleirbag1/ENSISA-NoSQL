"""Domain models for the product catalog.

This module owns the dataclasses and the invariants attached to the
``Product`` value object. It deliberately contains NO repository logic:
no database access, no querying, and no pagination arithmetic.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal


def now_utc() -> datetime:
    """Return the current time as a naive UTC ``datetime`` (second precision)."""
    return datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)


@dataclass(frozen=True)
class Category:
    """A product category reference carried by a product snapshot.

    ``id`` is opaque and unique per type. ``id=None`` is the client-side
    marker meaning "to be assigned by the repository": the repository
    ignores it on write, and on read the id is always populated.

    The in-memory reference implementation freezes ids at creation: a rename
    never re-issues them. Other implementations may re-issue the id on
    rename (for example, name-as-identity in a denormalized design); the
    delivered API and pages never rely on id stability across renames.
    """

    id: str | None
    name: str


@dataclass(frozen=True)
class Brand:
    """A product brand reference carried by a product snapshot.

    ``id`` is opaque and unique per type. ``id=None`` is the client-side
    marker meaning "to be assigned by the repository": the repository
    ignores it on write, and on read the id is always populated.

    The in-memory reference implementation freezes ids at creation: a rename
    never re-issues them. Other implementations may re-issue the id on
    rename (for example, name-as-identity in a denormalized design); the
    delivered API and pages never rely on id stability across renames.
    """

    id: str | None
    name: str


@dataclass(frozen=True)
class Product:
    """An immutable catalog product snapshot.

    ``frozen=True``: a ``Product`` is never mutated after creation.

    ``id`` is owned by the repository (the client never supplies it).

    ``created_at`` is naive UTC and defaults to "now" on the client-create
    path.

    ``category`` and ``brand`` hold entity references (:class:`Category` /
    :class:`Brand`) or ``None``: categories and brands are independently
    deletable, and deleting one DETACHES every product that referenced it
    (the product survives; its reference becomes ``None``). They are
    materialized at fetch time; a rename after the fetch does NOT update
    this instance; refetch for the truth.
    """

    id: str
    name: str
    description: str
    category: Category | None
    brand: Brand | None
    price: float
    stock: int
    rating: float
    units_sold: int
    created_at: datetime

    def __post_init__(self) -> None:
        if self.category is not None and not isinstance(self.category, Category):
            raise TypeError("category must be a Category or None")
        if self.brand is not None and not isinstance(self.brand, Brand):
            raise TypeError("brand must be a Brand or None")

    def get_category(self) -> Category | None:
        """Return the category entity of this snapshot, or ``None``.

        The entity reference is materialized at fetch time; a rename after
        the fetch does NOT update this instance; refetch for the truth.
        """
        return self.category

    def get_brand(self) -> Brand | None:
        """Return the brand entity of this snapshot, or ``None``.

        The entity reference is materialized at fetch time; a rename after
        the fetch does NOT update this instance; refetch for the truth.
        """
        return self.brand

    @classmethod
    def validate_payload(cls, payload: dict[str, Any]) -> dict[str, Any]:
        """Validate and normalize the eight mutable product fields of a payload.

        Shared by ``from_dict`` (create path) and the repository ``update``.
        Returns the normalized values for ``name``, ``description``,
        ``category``, ``brand``, ``price``, ``stock``, ``rating`` and
        ``units_sold``. The client NEVER supplies ``id`` or ``created_at``:
        any value present for those keys is ignored.

        Omitted fields take these defaults: ``rating`` -> ``0.0``,
        ``stock`` -> ``0``, ``units_sold`` -> ``0``, ``description`` ->
        ``""`` (empty string), and ``category`` / ``brand`` -> ``None``.
        ``name`` has NO default and is required.

        ``category`` and ``brand`` take a FREE-FORM string: a present value
        is stripped, and a non-blank result becomes
        ``Category(id=None, name=<stripped>)`` / ``Brand(id=None, ...)`` —
        ``id=None`` being the marker "to be assigned by the repository". A
        missing, null, empty or whitespace-only value yields ``None``.

        Raises:
            ValueError: if ``name`` is missing/empty, ``price`` is not a number
                or ``<= 0``, ``rating`` is not a number or outside ``[0, 5]``,
                ``stock`` is not an integer or ``< 0``, ``units_sold`` is not
                an integer or ``< 0``, or ``description`` is present but not a
                string, or ``category`` / ``brand`` is present but not a string
                ("category must be a string" / "brand must be a string").
        """
        name = payload.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("name must be a non-empty string")

        price = payload.get("price")
        if isinstance(price, bool) or not isinstance(price, (int, float)):
            raise ValueError("price must be a number")
        price = float(price)
        if price <= 0:
            raise ValueError("price must be > 0")

        rating = payload.get("rating")
        if rating is None:
            rating = 0.0
        if isinstance(rating, bool) or not isinstance(rating, (int, float)):
            raise ValueError("rating must be a number")
        rating = float(rating)
        if rating < 0.0 or rating > 5.0:
            raise ValueError("rating must be within [0, 5]")

        stock = payload.get("stock")
        if stock is None:
            stock = 0
        if isinstance(stock, bool) or not isinstance(stock, int):
            raise ValueError("stock must be an integer")
        if stock < 0:
            raise ValueError("stock must be >= 0")

        units_sold = payload.get("units_sold")
        if units_sold is None:
            units_sold = 0
        if isinstance(units_sold, bool) or not isinstance(units_sold, int):
            raise ValueError("units_sold must be an integer")
        if units_sold < 0:
            raise ValueError("units_sold must be >= 0")

        def _str(key: str) -> str:
            value = payload.get(key)
            if value is None:
                return ""
            if not isinstance(value, str):
                raise ValueError(f"{key} must be a string")
            return value

        def _entity(key: str, factory: type[Category] | type[Brand]) -> Category | Brand | None:
            value = payload.get(key)
            if value is None:
                return None
            if not isinstance(value, str):
                raise ValueError(f"{key} must be a string")
            entity_name = value.strip()
            if not entity_name:
                return None
            return factory(id=None, name=entity_name)

        return {
            "name": name,
            "description": _str("description"),
            "category": _entity("category", Category),
            "brand": _entity("brand", Brand),
            "price": price,
            "stock": stock,
            "rating": rating,
            "units_sold": units_sold,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> Product:
        """Build a ``Product`` from a client payload, validating invariants.

        The client NEVER supplies ``id`` or ``created_at``: any value present
        for those keys is ignored. ``id`` is set to an empty placeholder and is
        replaced by the repository in ``create_product`` / ``create_products``;
        ``created_at`` defaults to now (naive UTC).

        Raises:
            ValueError: same rules as :meth:`validate_payload`.
        """
        normalized = cls.validate_payload(payload)
        return cls(
            id="",  # placeholder; the repository generates the real id
            created_at=now_utc(),
            **normalized,
        )


@dataclass
class ProductQuery:
    """Filter / sort / pagination contract for ``list_products``.

    ``price_min`` / ``price_max`` are INCLUSIVE boundaries: a product whose
    ``price`` exactly equals ``price_min`` or ``price_max`` is matched.

    ``category`` and ``brand`` are filters by NAME (never by id): exact,
    case-sensitive, no trimming. ``None`` means "no filter".

    There is deliberately NO filter for "products without a category /
    brand": a documented gap of the query contract.

    Contract invariant: ties on ``sort_field`` are ALWAYS broken by ``id``
    ascending, in every backend, so both backends order ties identically.
    """

    category: str | None = None
    brand: str | None = None
    price_min: float | None = None  # inclusive
    price_max: float | None = None  # inclusive
    min_rating: float | None = None
    in_stock: bool | None = None
    search_text: str | None = None  # case-insensitive match on name OR description
    sort_field: Literal["name", "price", "rating", "units_sold", "created_at"] = "created_at"
    sort_ascending: bool = False
    page: int = 1  # 1-based
    page_size: int = 20  # clamped to [1, 100]


@dataclass
class ProductPage:
    """A single page of ``list_products`` results plus paging metadata."""

    items: list[Product]
    total: int
    page: int
    page_size: int
    total_pages: int


@dataclass
class CategoryStats:
    """Aggregate figures for one category.

    ``count`` is the number of products in the category.

    ``average_price`` is the mean price of the products in the category.

    ``total_value`` is the sum of ``price * stock`` across the category.
    """

    count: int
    average_price: float
    total_value: float


@dataclass
class CatalogStats:
    """Whole-catalog statistics.

    ``total`` is the number of products in the catalog: a plain COUNT of
    stored products, not a total price, not a total stock, and not a count
    of distinct product names. Every stored product counts, categorized or
    not, in stock or out of stock.

    ``average_price`` is the mean price over that same population of
    products.

    ``by_category`` contains only products that HAVE a category: keys are
    the current category NAMES, sorted by codepoint order. Products without
    a category are excluded from ``by_category`` (they still count in
    ``total`` / ``average_price``).
    """

    total: int
    average_price: float
    by_category: dict[str, CategoryStats]
